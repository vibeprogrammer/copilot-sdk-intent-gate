"""Copilot SDK permission handler backed by the intent gate."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session_events import PermissionRequestCustomTool

from intent_gate.gate import Caller, GateDecision, IntentGate

logger = logging.getLogger(__name__)

AuditFn = Callable[[dict[str, Any]], None]


def make_permission_handler(
    gate: IntentGate, caller: Caller, audit: AuditFn | None = None
) -> Callable[[Any, Any], Awaitable[Any]]:
    """Build an ``on_permission_request`` callback for one authenticated caller.

    Custom tool calls go through the gate. Every other permission kind (shell, file writes, URLs,
    MCP...) is rejected: this agent only needs its own tools. Any exception rejects.
    """

    def _record(entry: dict[str, Any]) -> None:
        if audit is not None:
            try:
                audit(entry)
            except Exception:  # an audit sink failure must not turn a deny into an allow
                logger.exception("audit sink failed")

    async def on_permission_request(request: Any, _invocation: Any) -> Any:
        try:
            if not isinstance(request, PermissionRequestCustomTool):
                kind = getattr(request, "kind", type(request).__name__)
                _record({"tool": None, "kind": kind, "allowed": False, "reason": "only custom tools are allowed"})
                return PermissionDecisionReject(feedback=f"Denied: {kind} is not allowed in this assistant.")
            started = time.perf_counter()
            decision: GateDecision = await gate.check(request.tool_name, request.args, caller)
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            _record({"tool": request.tool_name, "args": request.args, "gate_ms": elapsed_ms, **decision.as_dict()})
            if decision.allowed:
                return PermissionDecisionApproveOnce()
            return PermissionDecisionReject(feedback=f"Denied by authorization: {decision.reason}")
        except Exception as exc:
            logger.exception("permission handler failed")
            _record(
                {
                    "tool": getattr(request, "tool_name", None),
                    "allowed": False,
                    "reason": f"fail closed: {type(exc).__name__}",
                }
            )
            return PermissionDecisionReject(feedback="Denied: authorization check failed.")

    return on_permission_request
