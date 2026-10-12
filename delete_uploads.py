"""
Delete TV uploads recorded in state.json for a given date.

Deletes each matching content_id from the TV and removes it from state.json.
Defaults to today's date if --date is not given.

Usage:
  python delete_uploads.py                    # delete today's uploads
  python delete_uploads.py --date 2026-10-11  # delete a specific day
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("frametv.delete_uploads")


async def main(config_path: str, target_date: date) -> None:
    config = json.loads(Path(config_path).read_text())
    state_path = config.get("state_file", "./data/state.json")

    from frametv import state as state_mod
    from frametv.tv import TVWrapper

    state = state_mod.load_state(state_path)
    prefix = target_date.isoformat()

    to_delete = {
        cid: meta for cid, meta in state_mod.get_uploads(state).items()
        if meta.get("uploaded_at", "").startswith(prefix)
    }

    if not to_delete:
        log.info("No uploads found for %s — nothing to do", prefix)
        return

    log.info("Found %d upload(s) from %s", len(to_delete), prefix)

    tv = TVWrapper(config.get("tv", {}))
    if not await tv.connect():
        log.error("Could not connect to TV — aborting")
        sys.exit(1)

    try:
        for cid, meta in to_delete.items():
            ok = await tv.delete(cid)
            if ok:
                state_mod.mark_deleted(state, cid)
                log.info("Deleted: %s  (%s)", cid, Path(meta.get("source_key", "")).name)
            else:
                log.warning("Failed to delete %s from TV — leaving in state", cid)
    finally:
        await tv.close()
        state_mod.save_state(state_path, state)
        log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete TV uploads from a given date")
    parser.add_argument("--config", default="config.json")
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Date to purge (YYYY-MM-DD, default: today)",
    )
    args = parser.parse_args()
    try:
        target = date.fromisoformat(args.date)
    except ValueError:
        print(f"Invalid date: {args.date!r} — expected YYYY-MM-DD")
        sys.exit(1)
    asyncio.run(main(args.config, target))
