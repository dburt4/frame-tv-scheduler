from __future__ import annotations
import json
import logging
import random
from datetime import date, timedelta
from pathlib import Path
import aiohttp
from .base import ArtItem, ArtSource, HTTP_HEADERS

log = logging.getLogger(__name__)
_APOD_URL = "https://api.nasa.gov/planetary/apod"


class NASAApodSource(ArtSource):
    def __init__(self) -> None:
        self._items: list[ArtItem] = []
        self._session: aiohttp.ClientSession | None = None
        self._cache_dir: Path | None = None

    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        self._cache_dir = Path(config.get("cache_dir", "./data/cache/apod"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        api_key: str = config.get("api_key", "DEMO_KEY")
        cache_days: int = config.get("cache_days", 30)
        meta_file = self._cache_dir / "metadata.json"

        self._session = aiohttp.ClientSession(headers=HTTP_HEADERS)

        # Check if today's date is already cached
        cached: list[dict] = []
        if meta_file.exists():
            try:
                cached = json.loads(meta_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                log.warning("NASA APOD: could not read metadata cache %s: %s — starting fresh", meta_file, e)
                cached = []

        today_str = date.today().isoformat()
        if skip_cache:
            log.info("NASA APOD: skipping cache refresh (--skip-cache)")
        elif not any(e.get("date") == today_str for e in cached):
            log.info("Refreshing NASA APOD cache for the last %d days", cache_days)
            fresh = await self._fetch_batch(api_key, cache_days)
            if fresh:
                # Merge: keep existing entries not in the new batch, add new
                existing_dates = {e["date"] for e in fresh}
                merged = [e for e in cached if e["date"] not in existing_dates] + fresh
                meta_file.write_text(json.dumps(merged, indent=2))
                cached = merged

        # Build item list from cached entries that have a local image file
        for entry in cached:
            if entry.get("media_type") != "image":
                continue
            img_file = self._cache_dir / f"{entry['date']}.jpg"
            if img_file.exists():
                self._items.append(ArtItem(
                    key=entry["date"],
                    local_path=img_file,
                    fetch_url=entry.get("hdurl") or entry.get("url"),
                    title=entry.get("title", ""),
                ))
            elif entry.get("hdurl") or entry.get("url"):
                self._items.append(ArtItem(
                    key=entry["date"],
                    fetch_url=entry.get("hdurl") or entry.get("url"),
                    title=entry.get("title", ""),
                ))

        if self._items:
            log.info("NASA APOD pool: %d images", len(self._items))
        else:
            log.warning("NASA APOD pool is empty — no images available. Cache dir: %s", self._cache_dir)

    async def _fetch_batch(self, api_key: str, count: int) -> list[dict]:
        results: list[dict] = []
        try:
            async with self._session.get(
                _APOD_URL,
                params={"api_key": api_key, "count": count},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status == 200:
                    results = await resp.json()
                else:
                    log.warning("NASA APOD API returned %d", resp.status)
        except Exception as e:
            log.warning("NASA APOD fetch failed: %s", e)
        return [e for e in results if e.get("media_type") == "image"]

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
                log.warning("Failed to download APOD %s: HTTP %d (%s)", item.key, resp.status, item.fetch_url)
        except Exception as e:
            log.warning("Failed to download APOD %s: [%s] %s", item.key, type(e).__name__, e)
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
