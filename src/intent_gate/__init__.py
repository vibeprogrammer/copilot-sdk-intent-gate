"""Intent-gated permission handling for GitHub Copilot SDK agents.

Every custom tool call the agent wants to make is turned into a short statement of intent, sent to
IndyKite's open-source intent-agent (which binds the subject to the authenticated caller), and the
resulting AuthZEN evaluations are decided by any AuthZEN 1.0 decision engine (see ``intent_gate.pdp``).
Anything that goes wrong denies the call.
"""

from intent_gate.gate import Caller, GateDecision, IntentGate, ToolIntent
from intent_gate.handler import make_permission_handler
from intent_gate.pdp import PdpConfig, PdpConfigError, pdp_from_env

__all__ = [
    "Caller",
    "GateDecision",
    "IntentGate",
    "PdpConfig",
    "PdpConfigError",
    "ToolIntent",
    "make_permission_handler",
    "pdp_from_env",
]
