from __future__ import annotations
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path
import aiohttp
from .base import ArtItem, ArtSource, HTTP_HEADERS

log = logging.getLogger(__name__)
_BASE = "https://api.artic.edu/api/v1"
_IMG_BASE = "https://www.artic.edu/iiif/2"
_POOL_TTL_DAYS = 7


class ArtInstituteSource(ArtSource):
    def __init__(self) -> None:
        self._items: list[ArtItem] = []
        self._session: aiohttp.ClientSession | None = None
        self._cache_dir: Path | None = None

    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        self._cache_dir = Path(config.get("cache_dir", "./data/cache/aic"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        pool_size: int = config.get("pool_size", 100)
        query: str = config.get("query", "")
        self._session = aiohttp.ClientSession(headers=HTTP_HEADERS)
        pool_file = self._cache_dir / "pool.json"

        pool_data: dict = {}
        if pool_file.exists():
            try:
                pool_data = json.loads(pool_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Art Institute: could not read pool cache %s: %s — will rebuild", pool_file, e)
                pool_data = {}

        refreshed_at = pool_data.get("refreshed_at")
        needs_refresh = not refreshed_at or (
            datetime.fromisoformat(refreshed_at) < datetime.now() - timedelta(days=_POOL_TTL_DAYS)
        )

        if skip_cache:
            log.info("Art Institute: skipping cache refresh (--skip-cache)")
        elif needs_refresh:
            log.info("Refreshing Art Institute pool (query=%r, size=%d)", query, pool_size)
            entries = await self._build_pool(query, pool_size)
            pool_data = {"refreshed_at": datetime.now().isoformat(), "entries": entries}
            pool_file.write_text(json.dumps(pool_data, indent=2))

        for entry in pool_data.get("entries", []):
            if entry.get("image_id"):
                img_path = self._cache_dir / f"{entry['id']}.jpg"
                img_url = f"{_IMG_BASE}/{entry['image_id']}/full/843,/0/default.jpg"
                self._items.append(ArtItem(
                    key=str(entry["id"]),
                    local_path=img_path if img_path.exists() else None,
                    fetch_url=img_url,
                    title=entry.get("title", ""),
                    attribution=entry.get("artist", ""),
                ))

        if self._items:
            log.info("Art Institute pool: %d images", len(self._items))
        else:
            log.warning("Art Institute pool is empty — no images available. Cache dir: %s", self._cache_dir)

    async def _build_pool(self, query: str, pool_size: int) -> list[dict]:
        entries: list[dict] = []
        params = {
            "fields": "id,title,image_id,artist_display",
            "has_not_been_viewed_much": "false",
            "limit": 100,
            "page": 1,
        }
        if query:
            params["q"] = query
        # Fetch up to pool_size * 3 pages worth and sample down
        candidates: list[dict] = []
        for page in range(1, (pool_size * 3 // 100) + 2):
            params["page"] = page
            try:
                async with self._session.get(
                    f"{_BASE}/artworks/search" if query else f"{_BASE}/artworks",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        log.warning("Art Institute page %d: HTTP %d", page, resp.status)
                        break
                    data = await resp.json()
                    artworks = data.get("data", [])
                    if not artworks:
                        break
                    for aw in artworks:
                        if aw.get("image_id"):
                            candidates.append({
                                "id": aw["id"],
                                "image_id": aw["image_id"],
                                "title": aw.get("title", ""),
                                "artist": aw.get("artist_display", ""),
                            })
                    if len(candidates) >= pool_size * 3:
                        break
            except Exception as e:
                log.warning("Art Institute page %d fetch failed: [%s] %s", page, type(e).__name__, e)
                break

        sampled = random.sample(candidates, min(pool_size, len(candidates)))
        return sampled

    async def _download_image(self, item: ArtItem) -> Path | None:
        if item.local_path and item.local_path.exists():
            return item.local_path
        if not item.fetch_url or not self._cache_dir:
            return None
        dest = self._cache_dir / f"{item.key}.jpg"
        try:
            async with self._session.get(
                item.fetch_url,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    dest.write_bytes(await resp.read())
                    item.local_path = dest
                    return dest
                log.warning("Failed to download AIC artwork %s: HTTP %d", item.key, resp.status)
        except Exception as e:
            log.warning("Failed to download AIC artwork %s: [%s] %s", item.key, type(e).__name__, e)
        return None

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
            item = self._items[idx]
            await self._download_image(item)
            return item, (idx + 1) % len(self._items)

        exclude_set = set(exclude_keys)
        eligible = [it for it in self._items if it.key not in exclude_set]
        if not eligible:
            eligible = self._items[:]
        item = random.choice(eligible)
        await self._download_image(item)
        return item, last_index

    async def close(self) -> None:
        if self._session:
            await self._session.close()
