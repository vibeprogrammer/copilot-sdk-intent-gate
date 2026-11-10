"""End to end over real HTTP: the gate against the stand-in PDP and recorded intent-agent answers.

No model, no key, no IndyKite tenant: this is what CI runs. The live run is scripts/run_demo.py.
"""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import pytest

from canbank_assistant.tools import TOOL_INTENTS
from intent_gate import Caller, IntentGate
from standins import indykite_standin, replay_intent_agent

pytestmark = pytest.mark.anyio
KEY = "test-client-key"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _serve(handler: type) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def gate() -> Iterator[IntentGate]:
    indykite_standin.Handler.client_key = KEY
    pdp, pdp_url = _serve(indykite_standin.Handler)
    ia, ia_url = _serve(replay_intent_agent.make_handler(replay_intent_agent.load()))
    yield IntentGate(
        intent_agent_url=ia_url + "/",
        intent_agent_token="ci-token",
        pdp_url=pdp_url,
        pdp_headers={"X-IK-ClientKey": KEY},
        tools=TOOL_INTENTS,
        timeout_seconds=5,
    )
    pdp.shutdown()
    ia.shutdown()


@pytest.mark.parametrize(
    ("caller", "tool", "args", "allowed"),
    [
        ("bob", "get_account_balance", {"account_id": "acc-bob-checking"}, True),
        ("bob", "get_account_balance", {"account_id": "acc-alice-bob-joint"}, True),
        ("bob", "get_account_balance", {"account_id": "acc-alice-savings"}, False),
        ("carol", "get_account_balance", {"account_id": "acc-alice-savings"}, False),
        (
            "carol",
            "transfer_funds",
            {"from_account_id": "acc-alice-savings", "to_account_id": "acc-carol-checking", "amount": "500"},
            False,
        ),
        ("carol", "get_customer_profile", {"customer_id": "alice"}, False),
        ("alice", "get_invoice", {"invoice_id": "inv-alice-0412"}, True),
        # the limitation: the caller owns the account, so an injected transfer is allowed
        (
            "alice",
            "transfer_funds",
            {"from_account_id": "acc-alice-savings", "to_account_id": "acc-carol-checking", "amount": "500"},
            True,
        ),
    ],
)
async def test_recorded_decisions(gate: IntentGate, caller: str, tool: str, args: dict, allowed: bool) -> None:
    d = await gate.check(tool, args, Caller("Customer", caller))
    assert d.allowed is allowed, d.reason
    assert all(ev["subject"]["id"] == caller for ev in d.evaluations)


async def test_unrecorded_prompt_is_refused_and_fails_closed(gate: IntentGate) -> None:
    d = await gate.check("get_invoice", {"invoice_id": "inv-bob-0388"}, Caller("Customer", "carol"))
    assert not d.allowed
    assert "could not extract" in d.reason


async def test_wrong_client_key_fails_closed(gate: IntentGate) -> None:
    gate._pdp_headers = {"X-IK-ClientKey": "wrong"}
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, Caller("Customer", "bob"))
    assert not d.allowed
    assert "HTTP 401" in d.reason
