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
_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
_POOL_TTL_DAYS = 7


class MetMuseumSource(ArtSource):
    def __init__(self) -> None:
        self._items: list[ArtItem] = []
        self._session: aiohttp.ClientSession | None = None
        self._cache_dir: Path | None = None

    async def initialize(self, config: dict, skip_cache: bool = False) -> None:
        self._cache_dir = Path(config.get("cache_dir", "./data/cache/met"))
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        pool_size: int = config.get("pool_size", 100)
        dept_ids: list[int] = config.get("department_ids", [])
        self._session = aiohttp.ClientSession(headers=HTTP_HEADERS)
        pool_file = self._cache_dir / "pool.json"

        pool_data: dict = {}
        if pool_file.exists():
            try:
                pool_data = json.loads(pool_file.read_text())
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Met Museum: could not read pool cache %s: %s — will rebuild", pool_file, e)
                pool_data = {}

        refreshed_at = pool_data.get("refreshed_at")
        needs_refresh = not refreshed_at or (
            datetime.fromisoformat(refreshed_at) < datetime.now() - timedelta(days=_POOL_TTL_DAYS)
        )

        if skip_cache:
            log.info("Met Museum: skipping cache refresh (--skip-cache)")
        elif needs_refresh:
            log.info("Refreshing Met Museum pool (dept_ids=%s, size=%d)", dept_ids, pool_size)
            entries = await self._build_pool(dept_ids, pool_size)
            pool_data = {"refreshed_at": datetime.now().isoformat(), "entries": entries}
            pool_file.write_text(json.dumps(pool_data, indent=2))

        for entry in pool_data.get("entries", []):
            if entry.get("image_url"):
                img_path = self._cache_dir / f"{entry['object_id']}.jpg"
                self._items.append(ArtItem(
                    key=str(entry["object_id"]),
                    local_path=img_path if img_path.exists() else None,
                    fetch_url=entry["image_url"],
                    title=entry.get("title", ""),
                    attribution=entry.get("artist", ""),
                ))

        if self._items:
            log.info("Met Museum pool: %d images", len(self._items))
        else:
            log.warning("Met Museum pool is empty — no images available. Cache dir: %s", self._cache_dir)

    async def _build_pool(self, dept_ids: list[int], pool_size: int) -> list[dict]:
        # Fetch object IDs for each department
        all_ids: list[int] = []
        for dept_id in dept_ids:
            try:
                async with self._session.get(
                    f"{_BASE}/objects",
                    params={"departmentIds": dept_id, "hasImages": "true"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        all_ids.extend(data.get("objectIDs") or [])
                    else:
                        log.warning("Met Museum dept %d object list: HTTP %d", dept_id, resp.status)
            except Exception as e:
                log.warning("Met Museum dept %d fetch failed: [%s] %s", dept_id, type(e).__name__, e)

        if not all_ids:
            # Fetch public-domain objects with images if no departments given
            try:
                async with self._session.get(
                    f"{_BASE}/objects",
                    params={"hasImages": "true", "isPublicDomain": "true"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        all_ids = data.get("objectIDs") or []
                    else:
                        log.warning("Met Museum fallback object list: HTTP %d", resp.status)
            except Exception as e:
                log.warning("Met Museum fallback fetch failed: [%s] %s", type(e).__name__, e)

        if not all_ids:
            log.warning("Met Museum: no object IDs retrieved — pool will be empty")

        sampled = random.sample(all_ids, min(pool_size * 3, len(all_ids)))
        sem = asyncio.Semaphore(5)
        entries: list[dict] = []

        async def fetch_one(oid: int) -> dict | None:
            async with sem:
                try:
                    async with self._session.get(
                        f"{_BASE}/objects/{oid}",
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status == 200:
                            obj = await resp.json()
                            url = obj.get("primaryImageSmall") or obj.get("primaryImage")
                            if url:
                                return {
                                    "object_id": oid,
                                    "image_url": url,
                                    "title": obj.get("title", ""),
                                    "artist": obj.get("artistDisplayName", ""),
                                }
                        else:
                            log.debug("Met Museum object %d: HTTP %d", oid, resp.status)
                except Exception as e:
                    log.debug("Met Museum object %d fetch failed: [%s] %s", oid, type(e).__name__, e)
                return None

        tasks = [fetch_one(oid) for oid in sampled]
        results = await asyncio.gather(*tasks)
        for r in results:
            if r:
                entries.append(r)
            if len(entries) >= pool_size:
                break
        return entries[:pool_size]

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
                log.warning("Failed to download Met object %s: HTTP %d", item.key, resp.status)
        except Exception as e:
            log.warning("Failed to download Met object %s: %s", item.key, e)
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
