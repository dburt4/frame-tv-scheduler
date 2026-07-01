# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Rotates artwork on Samsung Frame TVs on a schedule. Pulls images from local folders, NASA APOD, the Metropolitan Museum of Art, and the Art Institute of Chicago. Runs on a home server via cron. Configured via config.json. No UI.

## Commands

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json

# Run (first run triggers TV pairing)
python3 run.py
python3 run.py --config path/to/config.json --skip-cache --log-file /var/log/frametv.log

# Tests
pytest
pytest tests/test_scheduler.py          # run a single test file
pytest tests/test_scheduler.py::test_name  # run a single test

# Cron job (typical usage)
# */30 * * * * cd /path/to/frame-tv-art && /path/to/venv/bin/python3 run.py
```

No linter is configured — no flake8, mypy, or black setup exists.

## Architecture

**Entry point**: `run.py` — loads config, initializes sources, connects to TV, evaluates which schedule rule is active, and rotates art. Includes fallback logic if the active source fails.

**Core modules** (`frametv/`):

- `tv.py` — `TVWrapper`: wraps `samsungtvws` async API; handles connection, token persistence, image upload/select/delete
- `scheduler.py` — evaluates which schedule rule is currently active (first-match wins; order matters)
- `state.py` — JSON-based persistence at `data/state.json`; tracks last rotation time, current index, recently-shown images, and uploaded content IDs
- `uploader.py` — resizes/converts images to Frame TV specs (max 3840×2160, 8 MB, RGB JPEG), deduplicates via SHA256, manages upload→state lifecycle
- `expiry.py` — deletes old API uploads from the TV after their TTL (only for sources with `"expires": true`)
- `sources/` — pluggable art sources that all implement the `ArtSource` ABC (`initialize`, `get_next`, `close`)

**Sources** (`frametv/sources/`):
- `local.py` — scans local directories; deterministic sort
- `nasa_apod.py` — fetches NASA APOD via API, caches metadata + images locally
- `met_museum.py` — queries Met Museum API; builds a random pool with 7-day TTL
- `art_institute.py` — Art Institute of Chicago API; supports optional `query` filter

## Key Concepts

**Schedule rules**: Ordered list in `config.json`. First matching rule wins. Conditions include `date` (YYYY-MM-DD or MM-DD for annual), `date_range` (supports year-wrap), `weekdays`, `time_window`. A rule with no conditions is the default/fallback.

**Deduplication**: Images are hashed (SHA256) before upload; if the TV already has the content, it selects the existing one rather than re-uploading.

**Portrait handling**: Per-source option — `"skip"` drops portrait images, `"blur"` creates a blurred letterbox background.

**Expiry**: API-sourced uploads can be marked `"expires": true` with a `ttl_days` value so they're auto-deleted from the TV to avoid filling storage.

**State file** (`data/state.json`): Tracks `last_change_at`, `active_rule_name`, `last_index`, `recently_shown` per schedule name, plus a map of `content_id` → upload metadata. Do not manually edit while the script is running.
