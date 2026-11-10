import pytest
from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
from copilot.session_events import PermissionRequestCustomTool, PermissionRequestShell

from intent_gate import Caller, GateDecision, make_permission_handler

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeGate:
    def __init__(self, decision: GateDecision | Exception) -> None:
        self.decision = decision
        self.calls: list[tuple] = []

    async def check(self, tool, args, caller):
        self.calls.append((tool, args, caller))
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


def custom(tool: str = "get_account_balance", args: dict | None = None) -> PermissionRequestCustomTool:
    return PermissionRequestCustomTool(tool_description="d", tool_name=tool, args=args or {"account_id": "a"})


async def test_allow_maps_to_approve_once() -> None:
    gate = FakeGate(GateDecision(True, "authorized"))
    audit: list[dict] = []
    handler = make_permission_handler(gate, Caller("Customer", "bob"), audit=audit.append)
    result = await handler(custom(), {})
    assert isinstance(result, PermissionDecisionApproveOnce)
    assert gate.calls == [("get_account_balance", {"account_id": "a"}, Caller("Customer", "bob"))]
    assert audit[0]["allowed"] is True


async def test_deny_maps_to_reject_with_reason() -> None:
    handler = make_permission_handler(FakeGate(GateDecision(False, "not authorized: X")), Caller("Customer", "bob"))
    result = await handler(custom(), {})
    assert isinstance(result, PermissionDecisionReject)
    assert "not authorized: X" in result.feedback


async def test_gate_exception_rejects() -> None:
    handler = make_permission_handler(FakeGate(RuntimeError("boom")), Caller("Customer", "bob"))
    assert isinstance(await handler(custom(), {}), PermissionDecisionReject)


async def test_non_custom_tool_kinds_are_rejected_without_asking_the_gate() -> None:
    gate = FakeGate(GateDecision(True, "authorized"))
    handler = make_permission_handler(gate, Caller("Customer", "bob"))
    shell = PermissionRequestShell.from_dict(
        {
            "kind": "shell",
            "fullCommandText": "rm -rf /",
            "intention": "x",
            "commands": [],
            "possiblePaths": [],
            "possibleUrls": [],
            "hasWriteFileRedirection": False,
            "canOfferSessionApproval": False,
        }
    )
    assert isinstance(await handler(shell, {}), PermissionDecisionReject)
    assert gate.calls == []


async def test_audit_failure_does_not_turn_deny_into_allow() -> None:
    def broken_audit(_entry: dict) -> None:
        raise OSError("disk full")

    handler = make_permission_handler(
        FakeGate(GateDecision(False, "no")), Caller("Customer", "bob"), audit=broken_audit
    )
    assert isinstance(await handler(custom(), {}), PermissionDecisionReject)
