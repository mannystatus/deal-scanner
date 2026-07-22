"""Shared interface every network deep-link builder implements."""

from abc import ABC, abstractmethod
from urllib.parse import quote

from ..merchants import Merchant


class DeepLinkBuilder(ABC):
    """Turns a plain product URL into a tracked affiliate deep link."""

    @abstractmethod
    def build(self, merchant: Merchant, destination_url: str, sub_id: str = "") -> str:
        """Return a tracked deep link, or the original URL if not ready."""
        raise NotImplementedError

    @staticmethod
    def _encode(url: str) -> str:
        return quote(url, safe="")
