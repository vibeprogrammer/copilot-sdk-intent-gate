"""Integration: the gate with OpenFGA (a real open-source AuthZEN engine) as its PDP.

Needs a running OpenFGA started with ``--experimentals=authzen`` and ``OPENFGA_API_URL`` pointing at it;
skipped otherwise. The ``openfga`` CI job downloads the release binary and runs these. Intent-agent's
answers are the recorded ones (tests/fixtures), so no model or key is needed.
"""

import itertools
import os
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer

import httpx
import pytest

from canbank_assistant.ledger import Ledger
from canbank_assistant.tools import TOOL_INTENTS
from intent_gate import Caller, IntentGate, pdp_from_env
from scripts.openfga_setup import load_demo
from standins import replay_intent_agent
from standins.indykite_standin import decide
from tests.test_e2e_recorded import CASES

API = os.environ.get("OPENFGA_API_URL", "")
pytestmark = [
    pytest.mark.openfga,
    pytest.mark.skipif(not API, reason="set OPENFGA_API_URL to a running OpenFGA with --experimentals=authzen"),
]


@pytest.fixture(scope="module")
def store() -> tuple[str, str]:
    return load_demo(API, os.environ.get("OPENFGA_API_TOKEN", ""), name="canbank-ci")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _all_requests() -> list[dict]:
    g = Ledger.load().data
    resources = (
        [("Customer", c) for c in g["customers"]]
        + [("Account", a) for a in g["accounts"]]
        + [("Invoice", i) for i in g["invoices"]]
    )
    actions = sorted({a for spec in TOOL_INTENTS.values() for a in spec.actions})
    return [
        {"subject": {"type": "Customer", "id": s}, "action": {"name": a}, "resource": {"type": t, "id": r}}
        for s, a, (t, r) in itertools.product(g["customers"], actions, resources)
    ]


def test_openfga_agrees_with_the_demo_policy_rules_on_every_request(store: tuple[str, str]) -> None:
    """Every customer x action x resource: OpenFGA's AuthZEN answer equals the stand-in's rule."""
    store_id, model_id = store
    reqs = _all_requests()
    got: list[bool] = []
    for i in range(0, len(reqs), 50):  # OpenFGA takes at most 50 evaluations per boxcar request
        r = httpx.post(
            f"{API}/stores/{store_id}/access/v1/evaluations",
            json={"evaluations": reqs[i : i + 50]},
            headers={"Openfga-Authorization-Model-Id": model_id},
            timeout=10,
        )
        r.raise_for_status()
        got += [e["decision"] for e in r.json()["evaluations"]]
    want = [decide(q)[0] for q in reqs]
    assert len(got) == len(reqs)
    assert got == want
    # 3 own profiles + 5 owner/account pairs for balance (joint: both owners) + the same 5 for transfers + 4 invoices
    assert sum(want) == 17


def test_unknown_action_or_type_is_a_deny_not_an_error(store: tuple[str, str]) -> None:
    store_id, _ = store
    r = httpx.post(
        f"{API}/stores/{store_id}/access/v1/evaluations",
        json={
            "evaluations": [
                {
                    "subject": {"type": "Customer", "id": "alice"},
                    "action": {"name": "DELETE_ACCOUNT"},
                    "resource": {"type": "Account", "id": "acc-alice-savings"},
                },
                {
                    "subject": {"type": "Agent", "id": "x"},
                    "action": {"name": "VIEW_ACCOUNT_BALANCE"},
                    "resource": {"type": "Account", "id": "acc-alice-savings"},
                },
            ]
        },
        timeout=10,
    )
    assert r.status_code == 200
    assert [e["decision"] for e in r.json()["evaluations"]] == [False, False]


@pytest.fixture
def gate(store: tuple[str, str]) -> Iterator[IntentGate]:
    store_id, model_id = store
    pdp = pdp_from_env(
        {
            "PDP_KIND": "openfga",
            "OPENFGA_API_URL": API,
            "OPENFGA_STORE_ID": store_id,
            "OPENFGA_AUTHORIZATION_MODEL_ID": model_id,
            "OPENFGA_API_TOKEN": os.environ.get("OPENFGA_API_TOKEN", ""),
        }
    )
    ia = ThreadingHTTPServer(("127.0.0.1", 0), replay_intent_agent.make_handler(replay_intent_agent.load()))
    threading.Thread(target=ia.serve_forever, daemon=True).start()
    yield IntentGate(
        intent_agent_url=f"http://127.0.0.1:{ia.server_address[1]}/",
        intent_agent_token="ci-token",
        pdp_url=pdp.url,
        pdp_headers=pdp.headers,
        tools=TOOL_INTENTS,
        timeout_seconds=5,
    )
    ia.shutdown()


@pytest.mark.anyio
@pytest.mark.parametrize(("caller", "tool", "args", "allowed"), CASES)
async def test_recorded_decisions_with_openfga(
    gate: IntentGate, caller: str, tool: str, args: dict, allowed: bool
) -> None:
    d = await gate.check(tool, args, Caller("Customer", caller))
    assert d.allowed is allowed, d.reason


@pytest.mark.anyio
async def test_unknown_store_fails_closed(gate: IntentGate) -> None:
    gate._pdp_url = f"{API}/stores/01NOSUCHSTORE0000000000000"
    d = await gate.check("get_account_balance", {"account_id": "acc-bob-checking"}, Caller("Customer", "bob"))
    assert not d.allowed
    assert d.reason.startswith("fail closed")
