"""STAND-IN RFC 7662 token introspection endpoint, so intent-agent can run without an IdP.

intent-agent introspects the Bearer token of whoever calls it (here: the bank assistant app).
Any non-empty token is answered as active for client ``copilot-bank-assistant`` with the audience
intent-agent expects by default. Modelled on intent-agent's own manual_testing/mock_introspect.py.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        form = self.rfile.read(length).decode()
        active = "token=" in form and not form.startswith("token=&")
        payload = (
            {
                "active": True,
                "sub": "copilot-bank-assistant",
                "act": {"sub": "copilot-bank-assistant"},
                "aud": os.environ.get("EXPECTED_TOKEN_AUDIENCE", "intent_agent"),
            }
            if active
            else {"active": False}
        )
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    host = os.environ.get("INTROSPECT_HOST", "127.0.0.1")
    port = int(os.environ.get("INTROSPECT_PORT", "9001"))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
