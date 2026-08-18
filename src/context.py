"""
Defines the AgentContext, representing the core global state for the session.

Centralizes the active AgentMode, the CredentialVault for storage, and the
AIClient instance. Passed down to components like the Orchestrator, Observer,
and Automator to prevent duplicated state and ensure consistent access to
credentials and LLM capabilities.
"""

from models import AgentMode
from vault import CredentialVault
from client import AIClient


class AgentContext:

    def __init__(self, mode: AgentMode):
        self.mode = mode
        self.vault = CredentialVault()
        self.ai_client = AIClient()
