"""
Defines the AgentContext, representing the core global state for the session.

Centralizes the active AgentMode, the CredentialVault for storage, and the
AIClient instance. Passed down to components like the Orchestrator, Observer,
and Automator to prevent duplicated state and ensure consistent access to
credentials and LLM capabilities.
"""

from models import AgentMode
from vault import CredentialVault
from client import AIClientBase


class AgentContext:

    def __init__(self, mode: AgentMode, ai_client: AIClientBase):
        self.mode = mode
        self.ai_client = ai_client
        self.vault = CredentialVault()
