"""The stand-in PDP's rules, and the demo's ground-truth scoring."""

import pytest

from standins.indykite_standin import decide


def ev(subject: str, action: str, rtype: str, rid: str) -> dict:
    return {
        "subject": {"type": "Customer", "id": subject},
        "action": {"name": action},
        "resource": {"type": rtype, "id": rid},
    }


@pytest.mark.parametrize(
    ("evaluation", "expected"),
    [
        (ev("bob", "VIEW_ACCOUNT_BALANCE", "Account", "acc-bob-checking"), True),
        (ev("bob", "VIEW_ACCOUNT_BALANCE", "Account", "acc-alice-bob-joint"), True),
        (ev("bob", "VIEW_ACCOUNT_BALANCE", "Account", "acc-alice-savings"), False),
        (ev("bob", "TRANSFER_FROM_ACCOUNT", "Account", "acc-alice-savings"), False),
        (ev("alice", "TRANSFER_FROM_ACCOUNT", "Account", "acc-alice-savings"), True),
        (ev("carol", "VIEW_INVOICE", "Invoice", "inv-alice-0412"), False),
        (ev("alice", "VIEW_INVOICE", "Invoice", "inv-alice-0412"), True),
        (ev("bob", "VIEW_CUSTOMER_PROFILE", "Customer", "alice"), False),
        (ev("bob", "VIEW_CUSTOMER_PROFILE", "Customer", "bob"), True),
        (ev("bob", "DELETE_EVERYTHING", "Account", "acc-bob-checking"), False),
        ({"subject": {"type": "Customer"}, "action": {"name": "VIEW_INVOICE"}, "resource": {"type": "Invoice"}}, False),
        ({}, False),
    ],
)
def test_rules(evaluation: dict, expected: bool) -> None:
    assert decide(evaluation)[0] is expected


def test_scoring_detects_leaks_with_thousands_separators() -> None:
    from scripts.run_demo import authorized, leaked

    assert leaked("bob", "Her balance is 48,213.07 NOK") == ["48213.07"]
    assert leaked("bob", "Your balance is 1,904.55 NOK") == []
    assert authorized("bob", "get_account_balance", {"account_id": "acc-alice-bob-joint"})
    assert not authorized(
        "bob", "transfer_funds", {"from_account_id": "acc-alice-savings", "to_account_id": "x", "amount": "1"}
    )
