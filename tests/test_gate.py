import json

import httpx
import pytest

from intent_gate import Caller

from .helpers import a2a_result, evaluation, make_gate, ok_json, pdp_decisions

BOB = Caller("Customer", "bob")
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_allow_when_intent_covers_call_and_engine_permits() -> None:
    log: list[httpx.Request] = []
    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), pdp_decisions(True), log)
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert d.allowed, d.reason
    sent = json.loads(log[0].content)
    # the caller identity travels in metadata, never in the prompt
    assert sent["params"]["message"]["metadata"] == {"subject_type": "Customer", "subject_id": "bob"}
    assert sent["params"]["message"]["parts"][0]["text"] == "View the balance of Account acc-bob-checking"
    assert log[0].headers["Authorization"] == "Bearer app-token"
    assert log[1].url.path == "/access/v1/evaluations"


async def test_deny_when_engine_says_no() -> None:
    gate = make_gate(
        ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation(resource_id="acc-alice-savings")]})),
        pdp_decisions(False),
    )
    d = await gate.check("get_account_balance", {"account_id": "acc-alice-savings"}, BOB)
    assert not d.allowed
    assert d.reason.startswith("not authorized")


@pytest.mark.parametrize("decision", [None, "true", 1, "permit"])
async def test_only_literal_true_permits(decision: object) -> None:
    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), pdp_decisions(decision))
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed


async def test_intent_agent_jsonrpc_error_fails_closed() -> None:
    gate = make_gate(
        ok_json({"jsonrpc": "2.0", "id": "1", "error": {"code": -32603, "message": "model down"}}), pdp_decisions(True)
    )
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert d.reason.startswith("fail closed")


async def test_intent_agent_refusal_shape_fails_closed() -> None:
    refusal = {
        "prompt": "p",
        "error": "Unable to extract intent from prompt.",
        "reason": "unclear",
        "obligation": "ask",
    }
    gate = make_gate(ok_json(a2a_result(refusal)), pdp_decisions(True))
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert "could not extract" in d.reason


@pytest.mark.parametrize("status", [401, 500, 502, 503])
async def test_intent_agent_http_error_fails_closed(status: int) -> None:
    gate = make_gate(lambda _r: httpx.Response(status), pdp_decisions(True))
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert f"HTTP {status}" in d.reason


async def test_intent_agent_timeout_fails_closed() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    gate = make_gate(hang, pdp_decisions(True))
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert "timeout" in d.reason


async def test_pdp_timeout_fails_closed() -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), hang)
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert "timeout" in d.reason


async def test_pdp_unreachable_fails_closed() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), refuse)
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed


async def test_non_json_and_wrong_task_state_fail_closed() -> None:
    gate = make_gate(lambda _r: httpx.Response(200, text="<html>"), pdp_decisions(True))
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed
    gate = make_gate(
        ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]}, state="TASK_STATE_FAILED")),
        pdp_decisions(True),
    )
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed


async def test_deny_when_intent_names_a_different_resource() -> None:
    # intent-agent understood something else than the call: the engine's yes must not count
    gate = make_gate(
        ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation(resource_id="acc-bob-checking")]})),
        pdp_decisions(True),
    )
    d = await gate.check("get_account_balance", {"account_id": "acc-alice-savings"}, BOB)
    assert not d.allowed
    assert "does not cover" in d.reason


async def test_deny_when_action_is_not_expected() -> None:
    gate = make_gate(
        ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation(action="HAS")]})), pdp_decisions(True)
    )
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed


async def test_deny_when_subject_is_not_the_caller() -> None:
    gate = make_gate(
        ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation(subject_id="alice")]})), pdp_decisions(True)
    )
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert "is not the caller" in d.reason


async def test_deny_when_decision_count_differs() -> None:
    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), pdp_decisions(True, True))
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed


async def test_one_denied_evaluation_denies_the_call() -> None:
    evs = [evaluation(), evaluation(resource_id="acc-alice-savings")]
    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": evs})), pdp_decisions(True, False))
    assert not (await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)).allowed


@pytest.mark.parametrize(
    ("tool", "args", "caller"),
    [
        ("unknown_tool", {"account_id": "acc-bob-checking"}, BOB),
        ("get_account_balance", {}, BOB),
        ("get_account_balance", "acc-bob-checking", BOB),
        ("get_account_balance", {"account_id": "acc-bob-checking"}, Caller("Customer", "")),
    ],
)
async def test_deny_before_any_network_call(tool: str, args: object, caller: Caller) -> None:
    log: list[httpx.Request] = []
    gate = make_gate(ok_json(a2a_result({"prompt": "p", "evaluations": [evaluation()]})), pdp_decisions(True), log)
    assert not (await gate.check(tool, args, caller)).allowed
    assert log == []


async def test_unexpected_exception_fails_closed() -> None:
    def boom(_r: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    gate = make_gate(boom, pdp_decisions(True))
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, BOB)
    assert not d.allowed
    assert d.reason == "fail closed: unexpected RuntimeError"
