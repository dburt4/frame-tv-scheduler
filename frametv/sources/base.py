from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# Sent with every outbound HTTP request. Some image servers (AIC IIIF, etc.)
# return 403 when they see the default aiohttp User-Agent.
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; frame-tv-art/1.0; +https://github.com/your-repo)"
}


@dataclass
class ArtItem:
    key: str
    local_path: Path | None = None
    fetch_url: str | None = None
    title: str = ""
    attribution: str = ""


class ArtSource(ABC):
    @abstractmethod
    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        """One-time setup: build pool, check caches, etc.
        skip_cache: if True, skip network refresh and use whatever is already on disk."""

    @abstractmethod
    async def get_next(
        self,
        exclude_keys: list[str],
        last_index: int,
        mode: str,
    ) -> tuple[ArtItem | None, int]:
        """
        Return the next item to display and the updated sequential index.
        Returns (None, last_index) if no eligible item could be found.
        mode: "random" or "sequential"
        """

    async def close(self) -> None:
        pass
