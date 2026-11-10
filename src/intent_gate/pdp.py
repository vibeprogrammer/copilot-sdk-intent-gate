"""Where the gate gets its decisions: any AuthZEN 1.0 Policy Decision Point.

The gate only ever calls ``POST {url}/access/v1/evaluations`` with intent-agent's evaluations, unchanged.
What differs between engines is the base URL and the auth header, so that is all this module knows.

``PDP_KIND`` picks one of:

* ``authzen`` - any AuthZEN 1.0 PDP. ``AUTHZEN_PDP_URL`` is the base URL; ``AUTHZEN_PDP_TOKEN`` (optional)
  is sent as ``Authorization: Bearer``; ``AUTHZEN_PDP_HEADER_NAME`` / ``AUTHZEN_PDP_HEADER_VALUE`` (optional)
  add one more header for engines with their own scheme.
* ``openfga`` - OpenFGA with ``--experimentals=authzen``. ``OPENFGA_API_URL`` + ``OPENFGA_STORE_ID`` give
  ``{api}/stores/{store_id}``; ``OPENFGA_API_TOKEN`` (optional, a preshared key) is sent as Bearer;
  ``OPENFGA_AUTHORIZATION_MODEL_ID`` (optional) pins the model with ``Openfga-Authorization-Model-Id``.
* ``indykite`` - IndyKite's AuthZEN endpoints. ``AUTHZEN_PDP_URL`` is the regional API base URL and
  ``AUTHZEN_PDP_CLIENT_KEY`` (required) the AppAgent credentials token, sent as ``X-IK-ClientKey``.
* ``standin`` - this repo's local stand-in (``standins/indykite_standin.py``), which mimics IndyKite's
  header. ``AUTHZEN_PDP_URL`` defaults to ``http://127.0.0.1:9002``.

When ``PDP_KIND`` is unset the kind is ``indykite`` if ``AUTHZEN_PDP_CLIENT_KEY`` is set (the behaviour
before this setting existed) and ``standin`` otherwise. Every kind may also set ``AUTHZEN_PDP_TOKEN``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

PDP_KINDS = ("authzen", "openfga", "indykite", "standin")
STANDIN_URL = "http://127.0.0.1:9002"


class PdpConfigError(ValueError):
    """The PDP settings are incomplete or contradictory. Raised at startup, never during a check."""


@dataclass(frozen=True)
class PdpConfig:
    kind: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        """For logs and transcripts: the kind, the URL and the header names (never their values)."""
        names = ", ".join(sorted(self.headers)) or "no auth header"
        return f"{self.kind} at {self.url} ({names})"


def _get(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _need(env: Mapping[str, str], name: str, kind: str) -> str:
    value = _get(env, name)
    if not value:
        raise PdpConfigError(f"PDP_KIND={kind} needs {name}")
    return value


def _openfga(env: Mapping[str, str]) -> tuple[str, dict[str, str], str]:
    api = _need(env, "OPENFGA_API_URL", "openfga").rstrip("/")
    url = f"{api}/stores/{_need(env, 'OPENFGA_STORE_ID', 'openfga')}"
    headers: dict[str, str] = {}
    if _get(env, "OPENFGA_AUTHORIZATION_MODEL_ID"):
        headers["Openfga-Authorization-Model-Id"] = _get(env, "OPENFGA_AUTHORIZATION_MODEL_ID")
    return url, headers, _get(env, "OPENFGA_API_TOKEN") or _get(env, "AUTHZEN_PDP_TOKEN")


def _extra_headers(env: Mapping[str, str], kind: str) -> dict[str, str]:
    key = _get(env, "AUTHZEN_PDP_CLIENT_KEY")
    if kind == "indykite":
        return {"X-IK-ClientKey": _need(env, "AUTHZEN_PDP_CLIENT_KEY", kind)}
    if kind == "standin":
        return {"X-IK-ClientKey": key} if key else {}
    # generic AuthZEN
    if key:
        raise PdpConfigError(
            "AUTHZEN_PDP_CLIENT_KEY is IndyKite's header; use PDP_KIND=indykite, or "
            "AUTHZEN_PDP_HEADER_NAME / AUTHZEN_PDP_HEADER_VALUE for another engine's header"
        )
    name, value = _get(env, "AUTHZEN_PDP_HEADER_NAME"), _get(env, "AUTHZEN_PDP_HEADER_VALUE")
    if bool(name) != bool(value):
        raise PdpConfigError("set both AUTHZEN_PDP_HEADER_NAME and AUTHZEN_PDP_HEADER_VALUE, or neither")
    return {name: value} if name else {}


def pdp_from_env(env: Mapping[str, str]) -> PdpConfig:
    """Build the PDP settings from environment-style variables. Raises PdpConfigError when incomplete."""
    kind = _get(env, "PDP_KIND").lower()
    if not kind:
        kind = "indykite" if _get(env, "AUTHZEN_PDP_CLIENT_KEY") else "standin"
    if kind not in PDP_KINDS:
        raise PdpConfigError(f"PDP_KIND must be one of {', '.join(PDP_KINDS)}, not {kind!r}")
    if kind == "openfga":
        url, headers, token = _openfga(env)
    else:
        url = _get(env, "AUTHZEN_PDP_URL") or (STANDIN_URL if kind == "standin" else "")
        if not url:
            raise PdpConfigError(f"PDP_KIND={kind} needs AUTHZEN_PDP_URL")
        headers, token = _extra_headers(env, kind), _get(env, "AUTHZEN_PDP_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if not url.startswith(("http://", "https://")):
        raise PdpConfigError(f"PDP URL must be http(s), got {url!r}")
    return PdpConfig(kind=kind, url=url.rstrip("/"), headers=headers)
