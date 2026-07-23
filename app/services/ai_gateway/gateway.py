"""
AI Gateway

Acts as a central registry for all AI providers.

Responsibilities
----------------
- Register providers
- Return provider instances
- Decouple routes from provider implementations
"""

from __future__ import annotations

from .providers.main import MainProvider
from .providers.premium import PremiumProvider
from .providers.free import FreeProvider
from .providers.notice import NoticeProvider
from .providers.summarizer import SummarizerProvider


class AIGateway:
    """
    Registry of available AI providers.
    """

    def __init__(self):
        self._providers = {
            "main": MainProvider(),
            "premium": PremiumProvider(),
            "free": FreeProvider(),
            "notice": NoticeProvider(),
            "summarizer": SummarizerProvider(),
        }

    def get_provider(self, provider: str):
        """
        Return provider instance.

        Raises:
            ValueError: if provider is not registered.
        """

        try:
            return self._providers[provider.lower()]
        except KeyError:
            raise ValueError(f"Unknown AI provider: {provider}")

    def available_providers(self) -> list[str]:
        """
        Return list of registered providers.
        """

        return list(self._providers.keys())


# Singleton instance
ai_gateway = AIGateway()