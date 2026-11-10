"""In-memory bank data for the demo, loaded from standins/demo_graph.json.

The tools below deliberately trust their arguments: they look up whatever id the model passes.
That is the common shape of agent tools, and the thing the gate exists to cover.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

DEFAULT_GRAPH = Path(__file__).resolve().parents[2] / "standins" / "demo_graph.json"


@dataclass
class Ledger:
    data: dict[str, Any]
    executions: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path = DEFAULT_GRAPH) -> Ledger:
        return cls(copy.deepcopy(json.loads(path.read_text())))

    def _log(self, tool: str, args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.executions.append({"tool": tool, "args": args, "result": result})
        return result

    def customer_profile(self, customer_id: str) -> dict[str, Any]:
        c = self.data["customers"].get(customer_id)
        if c is None:
            return self._log("get_customer_profile", {"customer_id": customer_id}, {"error": "no such customer"})
        accounts = sorted(a for a, v in self.data["accounts"].items() if customer_id in v["owners"])
        invoices = sorted(i for i, v in self.data["invoices"].items() if v["customer"] == customer_id)
        return self._log(
            "get_customer_profile",
            {"customer_id": customer_id},
            {"customer_id": customer_id, **c, "accounts": accounts, "invoices": invoices},
        )

    def account_balance(self, account_id: str) -> dict[str, Any]:
        a = self.data["accounts"].get(account_id)
        if a is None:
            return self._log("get_account_balance", {"account_id": account_id}, {"error": "no such account"})
        return self._log(
            "get_account_balance",
            {"account_id": account_id},
            {"account_id": account_id, "account_type": a["account_type"], "balance": a["balance"]},
        )

    def invoice(self, invoice_id: str) -> dict[str, Any]:
        i = self.data["invoices"].get(invoice_id)
        if i is None:
            return self._log("get_invoice", {"invoice_id": invoice_id}, {"error": "no such invoice"})
        return self._log("get_invoice", {"invoice_id": invoice_id}, {"invoice_id": invoice_id, **i})

    def transfer(self, from_account_id: str, to_account_id: str, amount: str) -> dict[str, Any]:
        args = {"from_account_id": from_account_id, "to_account_id": to_account_id, "amount": amount}
        src, dst = self.data["accounts"].get(from_account_id), self.data["accounts"].get(to_account_id)
        try:
            value = Decimal(str(amount).replace("NOK", "").strip())
        except InvalidOperation:
            return self._log("transfer_funds", args, {"error": "amount is not a number"})
        if src is None or dst is None or value <= 0:
            return self._log("transfer_funds", args, {"error": "invalid transfer"})
        for acc, sign in ((src, -1), (dst, 1)):
            bal = Decimal(acc["balance"].split()[0]) + sign * value
            acc["balance"] = f"{bal:.2f} NOK"
        return self._log(
            "transfer_funds",
            args,
            {"status": "completed", "amount": f"{value:.2f} NOK", "from": from_account_id, "to": to_account_id},
        )
