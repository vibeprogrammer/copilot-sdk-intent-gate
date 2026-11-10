"""Settings from the environment. See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from intent_gate.pdp import PdpConfig, pdp_from_env


@dataclass(frozen=True)
class Settings:
    intent_agent_url: str
    intent_agent_token: str
    pdp: PdpConfig
    model: str
    provider: dict[str, Any] | None
    gate_timeout_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        ptype = os.environ.get("MODEL_PROVIDER_TYPE", "").strip()
        provider: dict[str, Any] | None = None
        if ptype:  # BYOK; without it the Copilot SDK uses your GitHub Copilot sign-in
            provider = {"type": ptype, "base_url": os.environ["MODEL_BASE_URL"]}
            if os.environ.get("MODEL_API_KEY"):
                provider["api_key"] = os.environ["MODEL_API_KEY"]
            if os.environ.get("MODEL_WIRE_API"):
                provider["wire_api"] = os.environ["MODEL_WIRE_API"]
        return cls(
            intent_agent_url=os.environ.get("INTENT_AGENT_URL", "http://127.0.0.1:6003/"),
            intent_agent_token=os.environ.get("INTENT_AGENT_TOKEN", ""),
            pdp=pdp_from_env(os.environ),
            model=os.environ.get("MODEL", "gpt-4.1-mini"),
            provider=provider,
            gate_timeout_seconds=float(os.environ.get("GATE_TIMEOUT_SECONDS", "20")),
        )
