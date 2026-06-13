from __future__ import annotations
import os
import random
from pathlib import Path
from .base import ArtItem, ArtSource

_DEFAULT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff"}


class LocalFolderSource(ArtSource):
    def __init__(self) -> None:
        self._items: list[ArtItem] = []

    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        extensions = {e.lower().lstrip(".") for e in config.get("extensions", list(_DEFAULT_EXTENSIONS))}
        paths: list[str] = config.get("paths", [])
        recursive: bool = config.get("recursive", True)
        found: list[Path] = []
        for root in paths:
            root_path = Path(root)
            if not root_path.exists():
                continue
            if recursive:
                for dirpath, _dirs, files in os.walk(root_path, followlinks=False):
                    for f in files:
                        p = Path(dirpath) / f
                        if p.suffix.lower().lstrip(".") in extensions:
                            found.append(p)
            else:
                for p in root_path.iterdir():
                    if p.is_file() and p.suffix.lower().lstrip(".") in extensions:
                        found.append(p)
        # Sort deterministically for stable sequential ordering
        found.sort(key=lambda p: p.name.lower())
        self._items = [ArtItem(key=str(p), local_path=p, title=p.stem) for p in found]

    async def get_next(
        self,
        exclude_keys: list[str],
        last_index: int,
        mode: str,
    ) -> tuple[ArtItem | None, int]:
        if not self._items:
            return None, last_index

        if mode == "sequential":
            idx = last_index % len(self._items)
            return self._items[idx], (idx + 1) % len(self._items)

        # random: exclude recently shown, reset if pool would be empty
        exclude_set = set(exclude_keys)
        eligible = [it for it in self._items if it.key not in exclude_set]
        if not eligible:
            eligible = self._items[:]
        item = random.choice(eligible)
        return item, last_index
