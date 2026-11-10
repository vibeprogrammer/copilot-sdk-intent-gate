"""Load the demo into a running OpenFGA: create a store, write the model, write the demo graph as tuples.

    openfga run --datastore-engine memory --experimentals=authzen &
    python scripts/openfga_setup.py --api http://127.0.0.1:8080 >> .env

Prints ``PDP_KIND``, ``OPENFGA_API_URL``, ``OPENFGA_STORE_ID`` and ``OPENFGA_AUTHORIZATION_MODEL_ID`` lines
for the gate. The model is pdp/openfga/model.json (the JSON form of model.fga); the tuples come from
standins/demo_graph.json, the same data the stand-in PDP and the bank tools read.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "pdp" / "openfga" / "model.json"
GRAPH = ROOT / "standins" / "demo_graph.json"


def demo_tuples(graph: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """The demo graph as OpenFGA relationship tuples."""
    g = graph or json.loads(GRAPH.read_text())
    out = [{"user": f"Customer:{c}", "relation": "identity", "object": f"Customer:{c}"} for c in g["customers"]]
    for acc_id, acc in g["accounts"].items():
        out += [{"user": f"Customer:{o}", "relation": "owner", "object": f"Account:{acc_id}"} for o in acc["owners"]]
        if acc["status"] == "open":
            out.append({"user": "Customer:*", "relation": "open", "object": f"Account:{acc_id}"})
    out += [
        {"user": f"Customer:{inv['customer']}", "relation": "customer", "object": f"Invoice:{inv_id}"}
        for inv_id, inv in g["invoices"].items()
    ]
    return out


def load_demo(api: str, token: str = "", name: str = "canbank-demo") -> tuple[str, str]:
    """Create a store with the demo model and tuples. Returns (store_id, authorization_model_id)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=api.rstrip("/"), headers=headers, timeout=10) as c:
        store = c.post("/stores", json={"name": name})
        store.raise_for_status()
        store_id = store.json()["id"]
        m = c.post(f"/stores/{store_id}/authorization-models", json=json.loads(MODEL.read_text()))
        m.raise_for_status()
        model_id = m.json()["authorization_model_id"]
        w = c.post(
            f"/stores/{store_id}/write",
            json={"writes": {"tuple_keys": demo_tuples()}, "authorization_model_id": model_id},
        )
        w.raise_for_status()
    return store_id, model_id


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--api", default=os.environ.get("OPENFGA_API_URL", "http://127.0.0.1:8080"))
    p.add_argument("--name", default="canbank-demo")
    a = p.parse_args()
    store_id, model_id = load_demo(a.api, os.environ.get("OPENFGA_API_TOKEN", ""), a.name)
    print("PDP_KIND=openfga")
    print(f"OPENFGA_API_URL={a.api.rstrip('/')}")
    print(f"OPENFGA_STORE_ID={store_id}")
    print(f"OPENFGA_AUTHORIZATION_MODEL_ID={model_id}")


if __name__ == "__main__":
    main()
