"""
Frame TV Art Rotator — cron-invoked entry point.

Run via cron on a Linux NAS, e.g.:
  */30 * * * * cd /path/to/frame-tv-art && python run.py >> /var/log/frametv.log 2>&1

First-run setup:
  1. Copy config.example.json to config.json and fill in your TV's IP address.
  2. Run: python run.py
  3. The TV will display a PIN — approve it on the TV. The token is saved automatically
     to the path in config["tv"]["token_file"]. Subsequent runs use it without a PIN.
  4. Get a free NASA API key at https://api.nasa.gov/ and set "nasa_api_key" in config.json
     (the default "DEMO_KEY" works at low volume: 30 req/hr).
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("frametv.run")


def _add_file_handler(log_file: str) -> None:
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)


def _build_source(source_name: str, source_cfg: dict, nasa_api_key: str):
    stype = source_cfg.get("type", "local")
    if stype == "local":
        from frametv.sources.local import LocalFolderSource
        return LocalFolderSource()
    if stype == "nasa_apod":
        from frametv.sources.nasa_apod import NASAApodSource
        # Inject the global API key unless overridden in the source config
        if "api_key" not in source_cfg:
            source_cfg = dict(source_cfg, api_key=nasa_api_key)
        return NASAApodSource()
    if stype == "met_museum":
        from frametv.sources.met_museum import MetMuseumSource
        return MetMuseumSource()
    if stype == "art_institute":
        from frametv.sources.art_institute import ArtInstituteSource
        return ArtInstituteSource()
    raise ValueError(f"Unknown source type: {stype!r}")


async def _rotate_with_fallback(active_rule, default_rule, sources, sources_cfg, tv, state, uploader_mod) -> bool:
    """Try to rotate art using active_rule's source. If it fails or isn't loaded,
    fall back to the default rule's source."""
    source_name = active_rule["source"]

    if source_name in sources:
        source_cfg = sources_cfg.get(source_name, {})
        ok = await uploader_mod.rotate_art(active_rule, sources[source_name], tv, state, source_cfg)
        if ok:
            return True
        log.warning("Source '%s' failed to produce an image for rule '%s'", source_name, active_rule["name"])
    else:
        log.warning("Source '%s' for rule '%s' is not loaded (failed to initialize?)", source_name, active_rule["name"])

    # Don't fall back if the active rule is already the default
    if default_rule is None:
        log.warning("No default rule configured; cannot fall back")
        return False
    if active_rule["name"] == default_rule["name"]:
        log.warning("Active rule is already the default; no further fallback")
        return False

    fallback_source = default_rule["source"]
    if fallback_source not in sources:
        log.warning("Default rule source '%s' is also not loaded; giving up", fallback_source)
        return False

    log.info("Falling back to default rule '%s' (source: %s)", default_rule["name"], fallback_source)
    fallback_cfg = sources_cfg.get(fallback_source, {})
    return await uploader_mod.rotate_art(default_rule, sources[fallback_source], tv, state, fallback_cfg)


async def main(config_path: str, skip_cache: bool = False) -> None:
    config_file = Path(config_path)
    if not config_file.exists():
        log.error("Config file not found: %s", config_path)
        sys.exit(1)

    try:
        config = json.loads(config_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error("Failed to load config: %s", e)
        sys.exit(1)

    state_path = config.get("state_file", "./data/state.json")
    nasa_api_key = config.get("nasa_api_key", "DEMO_KEY")

    from frametv import state as state_mod
    from frametv.scheduler import evaluate_active_rule, find_default_rule
    from frametv.tv import TVWrapper
    from frametv import expiry as expiry_mod
    from frametv import uploader as uploader_mod

    state = state_mod.load_state(state_path)
    now = datetime.now()

    # Initialize all configured sources
    sources_cfg: dict = config.get("sources", {})
    sources = {}
    for name, cfg in sources_cfg.items():
        src = _build_source(name, cfg, nasa_api_key)
        try:
            await src.initialize(cfg, skip_cache=skip_cache)
            sources[name] = src
        except Exception as e:
            log.warning("Failed to initialize source '%s': %s", name, e)

    tv_cfg: dict = config.get("tv", {})
    tv = TVWrapper(tv_cfg)
    tv_connected = False

    try:
        schedules: list[dict] = config.get("schedules", [])
        if not schedules:
            log.error("No schedules configured")
            return

        # Expire old API uploads before doing anything else
        tv_connected = await tv.connect()
        await expiry_mod.expire_old_uploads(state, tv, now)

        # Evaluate which rule is active right now
        active_rule = evaluate_active_rule(schedules, now)
        log.info("Active rule: '%s' (source: %s, mode: %s, interval: %s min)",
                 active_rule["name"], active_rule["source"],
                 active_rule.get("mode", "random"), active_rule.get("interval_minutes"))

        source_name = active_rule["source"]
        default_rule = find_default_rule(schedules)

        # Determine if we should change the image
        sched_state = state_mod.get_schedule_state(state, active_rule["name"])
        last_rule = sched_state.get("active_rule_name")
        last_change_str = sched_state.get("last_change_at")
        interval_minutes = active_rule.get("interval_minutes")
        rule_changed = last_rule != active_rule["name"]

        should_change = False
        if rule_changed:
            log.info("Rule changed from '%s' to '%s'; selecting new image", last_rule, active_rule["name"])
            should_change = True
        elif interval_minutes is None:
            log.info("interval_minutes is null; holding current image (rule: '%s')", active_rule["name"])
            should_change = False
        elif last_change_str is None:
            should_change = True
        else:
            try:
                last_change = datetime.fromisoformat(last_change_str)
                elapsed = now - last_change
                should_change = elapsed >= timedelta(minutes=interval_minutes)
                if not should_change:
                    remaining = timedelta(minutes=interval_minutes) - elapsed
                    log.info("Next change in %s (rule: '%s')", remaining, active_rule["name"])
            except (ValueError, TypeError):
                should_change = True

        if should_change:
            if not tv_connected:
                log.warning("TV unavailable; skipping art change")
            elif not await tv.is_art_mode():
                log.info("TV is not currently in art mode; skipping art change")
            else:
                ok = await _rotate_with_fallback(
                    active_rule, default_rule, sources, sources_cfg, tv, state, uploader_mod
                )

    except Exception as e:
        log.exception("Unexpected error: %s", e)
    finally:
        await tv.close()
        for src in sources.values():
            try:
                await src.close()
            except Exception:
                pass
        state_mod.save_state(state_path, state)
        log.info("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frame TV Art Rotator")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument(
        "--skip-cache",
        action="store_true",
        help="Skip API cache refresh checks (uses whatever is already on disk). Useful for local development.",
    )
    parser.add_argument(
        "--log-file",
        default=None,
        help="Path to a log file. Logs are written here in addition to stdout.",
    )
    args = parser.parse_args()
    if args.log_file:
        _add_file_handler(args.log_file)
    asyncio.run(main(args.config, skip_cache=args.skip_cache))
