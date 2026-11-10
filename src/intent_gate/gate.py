"""The gate: tool call -> intent-agent -> AuthZEN decisions -> allow or deny. Fail closed."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Caller:
    """The authenticated end user this agent session acts for. Set by the app, never by the model."""

    subject_type: str
    subject_id: str


@dataclass(frozen=True)
class ToolIntent:
    """How one custom tool's call is described to intent-agent, and what the answer must cover.

    ``template`` renders the call as a short sentence, e.g. "View the balance of Account {account_id}".
    ``resources`` maps tool arguments to the resource type they name; ``actions`` lists the
    policy actions that may authorize that resource. A call is allowed only if intent-agent returns an
    evaluation for every listed argument, with one of those actions, and the engine permits all of them.
    """

    template: str
    resources: dict[str, str]
    actions: frozenset[str]


@dataclass
class GateDecision:
    allowed: bool
    reason: str
    prompt: str | None = None
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[bool] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "prompt": self.prompt,
            "evaluations": self.evaluations,
            "decisions": self.decisions,
        }


class GateError(Exception):
    """Anything that stops the gate from reaching a positive decision. Always means deny."""


def _deny(reason: str, **kw: Any) -> GateDecision:
    return GateDecision(allowed=False, reason=reason, **kw)


class IntentGate:
    """Ask intent-agent what a tool call means for this caller, then ask the engine whether it is allowed.

    ``intent_agent_url`` is the A2A JSON-RPC endpoint of intent-agent; ``intent_agent_token`` is this
    application's own Bearer token (intent-agent introspects it; it identifies the app, not the user).
    ``pdp_url`` is the base URL of an AuthZEN 1.0 Policy Decision Point (``/access/v1/evaluations``).
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        intent_agent_url: str,
        intent_agent_token: str,
        pdp_url: str,
        tools: dict[str, ToolIntent],
        pdp_headers: dict[str, str] | None = None,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._intent_agent_url = intent_agent_url
        self._token = intent_agent_token
        self._pdp_url = pdp_url.rstrip("/")
        self._pdp_headers = pdp_headers or {}
        self._tools = tools
        self._timeout = timeout_seconds
        self._client = client

    async def check(self, tool_name: str, args: Any, caller: Caller) -> GateDecision:
        """Decide one tool call. Never raises: every failure is a deny with its reason."""
        try:
            return await self._check(tool_name, args, caller)
        except GateError as exc:
            return _deny(f"fail closed: {exc}")
        except Exception as exc:
            logger.exception("intent gate failed unexpectedly")
            return _deny(f"fail closed: unexpected {type(exc).__name__}")

    async def _check(self, tool_name: str, args: Any, caller: Caller) -> GateDecision:
        spec = self._tools.get(tool_name)
        if spec is None:
            return _deny(f"no intent mapping for tool {tool_name!r}")
        if not isinstance(args, dict):
            return _deny("tool arguments are not an object")
        if not caller.subject_id or not caller.subject_type:
            return _deny("no authenticated caller")
        missing = [name for name in spec.resources if args.get(name) in (None, "")]
        if missing:
            return _deny(f"missing resource argument(s): {', '.join(missing)}")
        try:
            prompt = spec.template.format(**{k: str(v) for k, v in args.items()})
        except (KeyError, IndexError, ValueError) as exc:
            return _deny(f"cannot render intent template: {exc}")

        evaluations = await self._extract(prompt, caller)
        problem = _coverage_problem(evaluations, spec, args, caller)
        if problem:
            return _deny(problem, prompt=prompt, evaluations=evaluations)
        decisions = await self._decide(evaluations)
        if len(decisions) != len(evaluations):
            return _deny("engine returned a different number of decisions", prompt=prompt, evaluations=evaluations)
        if not all(decisions):
            denied = [
                f"{e['action']['name']} on {e['resource']['type']} {e['resource'].get('id')}"
                for e, d in zip(evaluations, decisions, strict=True)
                if not d
            ]
            return _deny(
                f"not authorized: {'; '.join(denied)}", prompt=prompt, evaluations=evaluations, decisions=decisions
            )
        return GateDecision(True, "authorized", prompt=prompt, evaluations=evaluations, decisions=decisions)

    async def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            if self._client is not None:
                resp = await self._client.post(url, json=body, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise GateError(f"timeout calling {url}") from exc
        except httpx.HTTPError as exc:
            raise GateError(f"{type(exc).__name__} calling {url}") from exc
        if resp.status_code != httpx.codes.OK:
            raise GateError(f"HTTP {resp.status_code} from {url}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise GateError(f"non-JSON answer from {url}") from exc
        if not isinstance(data, dict):
            raise GateError(f"unexpected answer shape from {url}")
        return data

    async def _extract(self, prompt: str, caller: Caller) -> list[dict[str, Any]]:
        """Send the intent to intent-agent over A2A; return its AuthZEN evaluations."""
        body = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": "ROLE_USER",
                    "parts": [{"text": prompt}],
                    "messageId": str(uuid.uuid4()),
                    # The caller identity rides here, outside the prompt: intent-agent binds every
                    # evaluation's subject to it, whatever the text says.
                    "metadata": {"subject_type": caller.subject_type, "subject_id": caller.subject_id},
                }
            },
        }
        headers = {"A2A-Version": "1.0", "Authorization": f"Bearer {self._token}"}
        data = await self._post(self._intent_agent_url, body, headers)
        if "error" in data:
            raise GateError(f"intent-agent error: {data['error'].get('message', 'unknown')[:200]}")
        try:
            task = data["result"]["task"]
            state = task["status"]["state"]
            text = task["artifacts"][0]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GateError("intent-agent answer has no artifact") from exc
        if state != "TASK_STATE_COMPLETED":
            raise GateError(f"intent-agent task state {state}")
        try:
            intent = json.loads(text)
        except ValueError as exc:
            raise GateError("intent-agent artifact is not JSON") from exc
        if not isinstance(intent, dict):
            raise GateError("intent-agent artifact is not an object")
        if "error" in intent:
            raise GateError(f"intent-agent could not extract an intent: {intent.get('reason', intent['error'])}")
        evaluations = intent.get("evaluations")
        if not isinstance(evaluations, list) or not evaluations:
            raise GateError("intent-agent returned no evaluations")
        return evaluations

    async def _decide(self, evaluations: list[dict[str, Any]]) -> list[bool]:
        """AuthZEN 1.0 boxcar request: one decision per evaluation."""
        data = await self._post(
            f"{self._pdp_url}/access/v1/evaluations", {"evaluations": evaluations}, self._pdp_headers
        )
        results = data.get("evaluations")
        if not isinstance(results, list):
            raise GateError("engine answer has no evaluations list")
        # Only a literal JSON true is a permit.
        return [isinstance(r, dict) and r.get("decision") is True for r in results]


def _coverage_problem(
    evaluations: list[dict[str, Any]], spec: ToolIntent, args: dict[str, Any], caller: Caller
) -> str | None:
    """Return why the evaluations do not describe this call for this caller, or None if they do."""
    for ev in evaluations:
        if not isinstance(ev, dict):
            return "malformed evaluation"
        subject = ev.get("subject") or {}
        if subject.get("type") != caller.subject_type or str(subject.get("id")) != caller.subject_id:
            # intent-agent can keep a model-chosen subject for search patterns; a tool call never needs one.
            return f"evaluation subject {subject.get('type')}:{subject.get('id')} is not the caller"
        if not isinstance(ev.get("action"), dict) or not isinstance(ev.get("resource"), dict):
            return "malformed evaluation"
    for arg, rtype in spec.resources.items():
        want = str(args[arg])
        if not any(
            ev["resource"].get("type") == rtype
            and str(ev["resource"].get("id")) == want
            and ev["action"].get("name") in spec.actions
            for ev in evaluations
        ):
            return f"intent does not cover {arg}={want!r} as {rtype} with an expected action"
    return None
