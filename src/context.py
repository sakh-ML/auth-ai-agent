"""
src/context.py

Core data model for the study agent.

One AgentContext instance lives for the whole browser session and is
passed into every other component (observer, automator, orchestrator).
Nothing else should hold its own copy of credentials or state.
"""

from models import AgentMode
from vault import CredentialVault


class AgentContext:

    def __init__(self, mode: AgentMode):
        self.mode = mode
        self.vault = CredentialVault()
