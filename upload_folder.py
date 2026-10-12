"""
Bulk-upload all images from a folder to the Samsung Frame TV.

Skips images already recorded in state.json (matched by SHA-256 hash).
Image hashing and preparation run in parallel; TV uploads are serialized
(the TV handles one upload at a time) unless --concurrency is raised.

The currently displayed image is not changed unless --select-last is given.

Usage:
  python upload_folder.py /path/to/photos
  python upload_folder.py /path/to/photos --config config.json --concurrency 2
  python upload_folder.py /path/to/photos --portrait-handling blur --select-last
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("frametv.upload_folder")

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}


def _scan_folder(folder: Path) -> list[Path]:
    return sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
    )


async def _upload_one(
    path: Path,
    tv,
    state: dict,
    state_lock: asyncio.Lock,
    upload_sem: asyncio.Semaphore,
    executor: ThreadPoolExecutor,
    portrait_handling: str,
) -> str | None:
    """Return the content_id on success (new or existing), None on failure or portrait skip."""
    from frametv.uploader import _file_hash, prepare_image
    from frametv import state as state_mod

    loop = asyncio.get_running_loop()

    try:
        fhash = await loop.run_in_executor(executor, _file_hash, path)
    except OSError as e:
        log.warning("Cannot hash %s: %s", path.name, e)
        return None

    async with state_lock:
        existing = state_mod.find_upload_by_hash(state, fhash)
    if existing:
        content_id, _ = existing
        log.info("Already uploaded (skip): %s  [%s]", path.name, content_id)
        return content_id

    try:
        prepared = await loop.run_in_executor(executor, prepare_image, path, portrait_handling)
    except Exception as e:
        log.warning("Prepare failed for %s: %s", path.name, e)
        return None

    if prepared is None:
        log.info("Skipping portrait: %s", path.name)
        return None

    async with upload_sem:
        content_id = await tv.upload_only(prepared)

    if prepared != path:
        prepared.unlink(missing_ok=True)

    if not content_id:
        log.warning("Upload returned no content_id for %s", path.name)
        return None

    async with state_lock:
        state_mod.record_upload(state, content_id, {
            "source_name": "upload_folder",
            "source_key": str(path),
            "file_hash": fhash,
            "uploaded_at": datetime.now().isoformat(),
            "expires": False,
        })

    log.info("Uploaded: %s  ->  %s", path.name, content_id)
    return content_id


async def main(folder: Path, config_path: str, concurrency: int, portrait_handling: str, select_last: bool) -> None:
    config_file = Path(config_path)
    if not config_file.exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)

    try:
        config = json.loads(config_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to load config: %s", e)
        sys.exit(1)

    if not folder.is_dir():
        log.error("Not a directory: %s", folder)
        sys.exit(1)

    from frametv import state as state_mod
    from frametv.tv import TVWrapper

    state_path = config.get("state_file", "./data/state.json")
    state = state_mod.load_state(state_path)

    paths = _scan_folder(folder)
    if not paths:
        log.info("No images found in %s", folder)
        return
    log.info("Found %d image(s) in %s", len(paths), folder)

    tv = TVWrapper(config.get("tv", {}))
    connected = await tv.connect()
    if not connected:
        log.error("Could not connect to TV — aborting")
        sys.exit(1)

    state_lock = asyncio.Lock()
    upload_sem = asyncio.Semaphore(concurrency)

    try:
        with ThreadPoolExecutor() as executor:
            tasks = [
                _upload_one(p, tv, state, state_lock, upload_sem, executor, portrait_handling)
                for p in paths
            ]
            results: list[str | None | BaseException] = await asyncio.gather(*tasks, return_exceptions=True)

        succeeded = [r for r in results if isinstance(r, str)]
        failed = sum(1 for r in results if r is None or isinstance(r, BaseException))
        log.info("Done: %d succeeded, %d failed/skipped-portrait (of %d total)", len(succeeded), failed, len(paths))

        if select_last and succeeded:
            for path, result in reversed(list(zip(paths, results))):
                if isinstance(result, str):
                    ok = await tv.select_existing(result)
                    if ok:
                        log.info("Now displaying: %s", path.name)
                    break
    finally:
        await tv.close()
        state_mod.save_state(state_path, state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk-upload a folder of images to the Frame TV")
    parser.add_argument("folder", type=Path, help="Directory of images to upload")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max simultaneous TV uploads (default: 1; raise with caution)",
    )
    parser.add_argument(
        "--portrait-handling",
        choices=["skip", "blur"],
        default="blur",
        help="What to do with portrait-orientation images (default: blur)",
    )
    parser.add_argument(
        "--select-last",
        action="store_true",
        help="After uploading, display the last image in the folder on the TV",
    )
    args = parser.parse_args()
    asyncio.run(main(args.folder, args.config, args.concurrency, args.portrait_handling, args.select_last))
