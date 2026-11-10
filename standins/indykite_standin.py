"""STAND-IN for the IndyKite platform, for local runs and CI. This is not IndyKite.

It serves three things on one port:

* ``GET /data-schema/v1`` and ``GET /access/v1/policies`` - the two IndyKite endpoints the real
  intent-agent fetches its vocabulary from (paths as in intent-agent's schema.py and policy.py).
  The schema is intent-agent's own ``canbank`` test fixture; the policies are this demo's four
  KBAC policies in the listing shape intent-agent parses.
* ``POST /access/v1/evaluation`` and ``POST /access/v1/evaluations`` - a tiny AuthZEN 1.0
  Policy Decision Point. It does not run Cypher: each policy's condition is re-implemented below
  as an explicit Python rule over ``demo_graph.json``. With a real IndyKite project you point the
  gate's ``AUTHZEN_PDP_URL`` at IndyKite's own decision endpoint instead.

Every response carries ``X-Standin: indykite-standin`` so a transcript can never be mistaken for
a real IndyKite decision.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
GRAPH: dict[str, Any] = json.loads((HERE / "demo_graph.json").read_text())
SCHEMA: dict[str, Any] = json.loads((HERE / "canbank_schema.json").read_text())
POLICIES: dict[str, Any] = json.loads((HERE / "demo_policies.json").read_text())


def _owns(customer: str, account: str) -> bool:
    acc = GRAPH["accounts"].get(account)
    return bool(acc) and customer in acc["owners"]


# One rule per policy action, mirroring the Cypher condition in demo_policies.json.
RULES: dict[tuple[str, str], Callable[[str, str], bool]] = {
    # MATCH (subject:Customer) MATCH (resource:Customer) WHERE subject.external_id = resource.external_id
    ("VIEW_CUSTOMER_PROFILE", "Customer"): lambda s, r: s == r and s in GRAPH["customers"],
    # MATCH (subject:Customer)-[:OWNS]->(resource:Account)
    ("VIEW_ACCOUNT_BALANCE", "Account"): _owns,
    # MATCH (subject:Customer)-[:OWNS]->(resource:Account) WHERE resource.status = 'open'
    ("TRANSFER_FROM_ACCOUNT", "Account"): lambda s, r: _owns(s, r) and GRAPH["accounts"][r]["status"] == "open",
    # MATCH (subject:Customer)-[:HAS_INVOICE]->(resource:Invoice)
    ("VIEW_INVOICE", "Invoice"): lambda s, r: GRAPH["invoices"].get(r, {}).get("customer") == s,
}


def decide(evaluation: dict[str, Any]) -> tuple[bool, str]:
    """AuthZEN decision for one {subject, action, resource, context}. Default deny."""
    try:
        subject = evaluation["subject"]
        action = evaluation["action"]["name"]
        resource = evaluation["resource"]
    except (KeyError, TypeError):
        return False, "malformed evaluation"
    if subject.get("type") != "Customer" or not subject.get("id"):
        return False, "subject must be an identified Customer"
    if not resource.get("id"):
        return False, "resource id required (no search decisions in this stand-in)"
    rule = RULES.get((action, resource.get("type", "")))
    if rule is None:
        return False, f"no policy grants {action} on {resource.get('type')}"
    ok = rule(str(subject["id"]), str(resource["id"]))
    return ok, "policy condition met" if ok else "policy condition not met"


class Handler(BaseHTTPRequestHandler):
    server_version = "indykite-standin/0.1"
    client_key = ""

    def log_message(self, fmt: str, *args: object) -> None:  # quieter than the default
        if os.environ.get("STANDIN_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Standin", "indykite-standin")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _key_ok(self) -> bool:
        return not self.client_key or self.headers.get("X-IK-ClientKey") == self.client_key

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/health":
            self._send(200, {"status": "ok", "standin": True})
            return
        if not self._key_ok():
            self._send(401, {"error": "bad X-IK-ClientKey"})
            return
        if url.path == "/data-schema/v1":
            self._send(200, SCHEMA)
        elif url.path == "/access/v1/policies":
            subject_type = parse_qs(url.query).get("subject_type", [""])[0]
            results = [
                p for p in POLICIES["results"] if not subject_type or p["policy"]["subject"]["type"] == subject_type
            ]
            self._send(200, {"results": results})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not self._key_ok():
            self._send(401, {"error": "bad X-IK-ClientKey"})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            self._send(400, {"error": "invalid JSON"})
            return
        if url.path == "/access/v1/evaluation":
            ok, why = decide(body)
            self._send(200, {"decision": ok, "context": {"reason": why, "standin": True}})
        elif url.path == "/access/v1/evaluations":
            defaults = {k: body[k] for k in ("subject", "action", "resource", "context") if k in body}
            out = []
            for ev in body.get("evaluations") or []:
                ok, why = decide({**defaults, **ev})
                out.append({"decision": ok, "context": {"reason": why, "standin": True}})
            self._send(200, {"evaluations": out})
        else:
            self._send(404, {"error": "not found"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("STANDIN_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STANDIN_PORT", "9002")))
    args = parser.parse_args()
    Handler.client_key = os.environ.get("IK_APP_AGENT_KEY", "")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
