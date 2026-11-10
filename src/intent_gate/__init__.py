"""Intent-gated permission handling for GitHub Copilot SDK agents.

Every custom tool call the agent wants to make is turned into a short statement of intent, sent to
IndyKite's open-source intent-agent (which binds the subject to the authenticated caller), and the
resulting AuthZEN evaluations are decided by an authorization engine. Anything that goes wrong
denies the call.
"""

from intent_gate.gate import Caller, GateDecision, IntentGate, ToolIntent
from intent_gate.handler import make_permission_handler

__all__ = ["Caller", "GateDecision", "IntentGate", "ToolIntent", "make_permission_handler"]
