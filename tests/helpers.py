"""Fake intent-agent and AuthZEN PDP behind httpx.MockTransport, shaped like the real answers."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from intent_gate import IntentGate, ToolIntent

IA_URL = "http://intent-agent.test/"
PDP_URL = "http://pdp.test"

TOOLS = {
    "get_account_balance": ToolIntent(
        template="View the balance of Account {account_id}",
        resources={"account_id": "Account"},
        actions=frozenset({"VIEW_ACCOUNT_BALANCE"}),
    )
}


def evaluation(
    subject_id: str = "bob", resource_id: str = "acc-bob-checking", action: str = "VIEW_ACCOUNT_BALANCE"
) -> dict[str, Any]:
    return {
        "subject": {"type": "Customer", "id": subject_id},
        "action": {"name": action},
        "resource": {"type": "Account", "id": resource_id},
        "context": {"parameters": {}},
    }


def a2a_result(intent: dict[str, Any], state: str = "TASK_STATE_COMPLETED") -> dict[str, Any]:
    """The A2A JSON-RPC task envelope intent-agent answers SendMessage with."""
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"task": {"status": {"state": state}, "artifacts": [{"parts": [{"text": json.dumps(intent)}]}]}},
    }


Responder = Callable[[httpx.Request], httpx.Response]


def make_gate(
    intent_agent: Responder, pdp: Responder, log: list[httpx.Request] | None = None, timeout: float = 5.0
) -> IntentGate:
    def route(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        if request.url.host == "intent-agent.test":
            return intent_agent(request)
        return pdp(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(route))
    return IntentGate(
        intent_agent_url=IA_URL,
        intent_agent_token="app-token",
        pdp_url=PDP_URL,
        tools=TOOLS,
        client=client,
        timeout_seconds=timeout,
    )


def ok_json(body: Any) -> Responder:
    return lambda _req: httpx.Response(200, json=body)


def pdp_decisions(*decisions: Any) -> Responder:
    return ok_json({"evaluations": [{"decision": d} for d in decisions]})
