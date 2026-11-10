"""The shared CanBank assistant: one Copilot SDK agent, many signed-in customers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from copilot import CopilotClient
from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session_events import PermissionRequestCustomTool

from canbank_assistant.config import Settings
from canbank_assistant.ledger import Ledger
from canbank_assistant.tools import TOOL_INTENTS, build_tools
from intent_gate import Caller, IntentGate, make_permission_handler

TOOL_NAMES = list(TOOL_INTENTS)

SYSTEM_PROMPT = """You are the CanBank customer support assistant.
The signed-in customer is {name} (customer id: {customer_id}).
Only help the signed-in customer with their own profile, accounts and invoices. Never reveal another
customer's data and never move money out of an account the customer does not own.
Use the tools to look things up; keep answers short."""


def build_gate(settings: Settings) -> IntentGate:
    headers: dict[str, str] = {}
    if settings.pdp_client_key:  # IndyKite's AuthZEN endpoints take the AppAgent credentials token here
        headers["X-IK-ClientKey"] = settings.pdp_client_key
    if settings.pdp_token:  # optional user access token, for policies that read token claims
        headers["Authorization"] = f"Bearer {settings.pdp_token}"
    return IntentGate(
        intent_agent_url=settings.intent_agent_url,
        intent_agent_token=settings.intent_agent_token,
        pdp_url=settings.pdp_url,
        pdp_headers=headers,
        tools=TOOL_INTENTS,
        timeout_seconds=settings.gate_timeout_seconds,
    )


def ungated_handler(audit: list[dict[str, Any]]) -> Any:
    """The baseline: approve every custom tool call (the prompt is the only guard)."""

    async def handler(request: Any, _invocation: Any) -> Any:
        if isinstance(request, PermissionRequestCustomTool):
            audit.append({"tool": request.tool_name, "args": request.args, "allowed": True, "reason": "no gate"})
            return PermissionDecisionApproveOnce()
        audit.append({"tool": None, "allowed": False, "reason": "only custom tools are allowed"})
        return PermissionDecisionReject(feedback="Denied: only this assistant's own tools are allowed.")

    return handler


async def run_conversation(  # noqa: PLR0913
    client: CopilotClient,
    settings: Settings,
    customer_id: str,
    prompt: str,
    *,
    gated: bool,
    ledger: Ledger | None = None,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """One customer, one message, one fresh session. Returns a transcript record."""
    ledger = ledger or Ledger.load()
    customer = ledger.data["customers"][customer_id]
    caller = Caller(subject_type="Customer", subject_id=customer_id)  # from the bank's login, not the model
    permissions: list[dict[str, Any]] = []
    inner = (
        make_permission_handler(build_gate(settings), caller, audit=permissions.append)
        if gated
        else ungated_handler(permissions)
    )
    in_flight = 0
    settled = asyncio.Event()
    settled.set()

    async def on_permission(request: Any, invocation: Any) -> Any:
        # Count checks in flight: with parallel tool calls the model can finish its reply before the
        # gate has answered every call, and the transcript should still record each decision.
        nonlocal in_flight
        in_flight += 1
        settled.clear()
        try:
            return await inner(request, invocation)
        finally:
            in_flight -= 1
            if in_flight == 0:
                settled.set()

    session_args: dict[str, Any] = {
        "on_permission_request": on_permission,
        "model": settings.model,
        "tools": build_tools(ledger),
        "available_tools": TOOL_NAMES,
        "system_message": {
            "mode": "replace",
            "content": SYSTEM_PROMPT.format(name=customer["name"], customer_id=customer_id),
        },
    }
    if settings.provider:
        session_args["provider"] = settings.provider
    session = await client.create_session(**session_args)
    tool_requests: list[dict[str, Any]] = []

    def on_event(event: Any) -> None:
        if event.type.value == "tool.execution_start":
            data = event.data
            tool_requests.append({"tool": getattr(data, "tool_name", None), "args": getattr(data, "arguments", None)})

    session.on(on_event)
    reply = None
    error = None
    try:
        result = await session.send_and_wait(prompt, timeout=timeout)
        reply = result.data.content if result else None
    except TimeoutError as exc:
        error = f"timeout: {exc}"
    finally:
        try:
            await asyncio.wait_for(settled.wait(), timeout=settings.gate_timeout_seconds * 2 + 5)
        except TimeoutError:
            error = (error or "") + " gate checks still in flight at disconnect"
        await session.disconnect()
    return {
        "customer": customer_id,
        "gated": gated,
        "prompt": prompt,
        "tool_requests": tool_requests,
        "permission_decisions": permissions,
        "tool_executions": ledger.executions,
        "reply": reply,
        "error": error,
    }


async def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Ask the shared CanBank assistant something, as a customer.")
    parser.add_argument("--as", dest="customer", required=True, choices=["alice", "bob", "carol"])
    parser.add_argument("--no-gate", action="store_true", help="run without the intent gate (baseline)")
    parser.add_argument("prompt")
    args = parser.parse_args()
    settings = Settings.from_env()
    async with CopilotClient() as client:
        record = await run_conversation(client, settings, args.customer, args.prompt, gated=not args.no_gate)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
