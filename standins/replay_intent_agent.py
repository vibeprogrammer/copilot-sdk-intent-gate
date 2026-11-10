"""STAND-IN for intent-agent in CI: replays answers the real intent-agent gave on 2026-11-10.

Serves A2A ``SendMessage`` on one port. A known (caller, prompt) pair gets the recorded evaluations in
intent-agent's task envelope; anything else gets intent-agent's own refusal shape. It never calls a model.
Use the real intent-agent for anything but tests.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "recorded_intent_agent.json"


def load(path: Path = DEFAULT) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    data = json.loads(path.read_text())
    return {(r["subject_type"], r["subject_id"], r["prompt"]): r["evaluations"] for r in data["recordings"]}


def make_handler(recordings: dict[tuple[str, str, str], list[dict[str, Any]]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            if (
                not self.headers.get("Authorization", "").startswith("Bearer ")
                or self.headers.get("A2A-Version") != "1.0"
            ):
                self._send(401, {"error": "unauthenticated"})
                return
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            msg = req["params"]["message"]
            meta = msg.get("metadata") or {}
            prompt = msg["parts"][0]["text"]
            evaluations = recordings.get((meta.get("subject_type"), meta.get("subject_id"), prompt))
            intent: dict[str, Any] = (
                {"prompt": prompt, "evaluations": evaluations}
                if evaluations is not None
                else {
                    "prompt": prompt,
                    "error": "Unable to extract intent from prompt.",
                    "reason": "The prompt doesn't match the Knowledge Graph Schema, or is unclear.",
                    "obligation": "Ask the prompter to clarify their request or ensure it's relevant to the system.",
                }
            )
            task = {
                "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [{"parts": [{"text": json.dumps(intent)}]}],
            }
            self._send(200, {"jsonrpc": "2.0", "id": req.get("id"), "result": {"task": task}})

        def _send(self, status: int, body: object) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Standin", "intent-agent-replay")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


if __name__ == "__main__":
    port = int(os.environ.get("REPLAY_PORT", "6003"))
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(load())).serve_forever()
