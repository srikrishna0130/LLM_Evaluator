"""Shared contract for model clients.

Both the primary mock model and the shadow candidate model implement this
async interface, so the /evaluate flow and tests can depend on a single narrow
API (and swap in fakes) regardless of the concrete backend.
"""

from abc import ABC, abstractmethod


class BaseModelClient(ABC):
    """Abstract async client returning a normalized generation result.

    Implementations return a ``dict`` with at least ``text`` and ``model`` keys;
    the candidate additionally includes ``usage`` and ``latency_ms``.
    """

    @abstractmethod
    async def generate(self, prompt: str) -> dict:
        """Generate a response for ``prompt``."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any held resources (connection pools, etc.).

        Default is a no-op; override where a backend holds resources.
        """
        return None
