from __future__ import annotations
import os
import random
from pathlib import Path
from .base import ArtItem, ArtSource

_DEFAULT_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "bmp", "gif", "tiff"}


def scan_image_files(root: Path, extensions: set[str] = _DEFAULT_EXTENSIONS, recursive: bool = True) -> list[Path]:
    """Return image files under root, skipping hidden and Synology system dirs."""
    found: list[Path] = []
    if not root.exists():
        return found
    if recursive:
        for dirpath, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith(("@", "."))]
            for f in files:
                p = Path(dirpath) / f
                if p.suffix.lower().lstrip(".") in extensions:
                    found.append(p)
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower().lstrip(".") in extensions:
                found.append(p)
    found.sort(key=lambda p: p.name.lower())
    return found


class LocalFolderSource(ArtSource):
    def __init__(self) -> None:
        self._items: list[ArtItem] = []

    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        extensions = {e.lower().lstrip(".") for e in config.get("extensions", list(_DEFAULT_EXTENSIONS))}
        recursive: bool = config.get("recursive", True)
        found: list[Path] = []
        for root in config.get("paths", []):
            found.extend(scan_image_files(Path(root), extensions, recursive))
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
