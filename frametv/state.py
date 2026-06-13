from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

_EMPTY: dict = {"schedules": {}, "uploads": {}}


def _deep_copy(d: dict) -> dict:
    return json.loads(json.dumps(d))


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return _deep_copy(_EMPTY)
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return _deep_copy(_EMPTY)


def save_state(path: str | Path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, p)


def get_schedule_state(state: dict, name: str) -> dict:
    return state["schedules"].setdefault(name, {
        "last_change_at": None,
        "active_rule_name": None,
        "last_index": 0,
        "recently_shown": [],
    })


def record_shown(state: dict, schedule_name: str, key: str, mode: str, rule_name: str, max_recent: int = 20) -> None:
    s = get_schedule_state(state, schedule_name)
    s["active_rule_name"] = rule_name
    s["last_change_at"] = datetime.now().isoformat()
    recent: list = s.setdefault("recently_shown", [])
    if key not in recent:
        recent.append(key)
    if len(recent) > max_recent:
        s["recently_shown"] = recent[-max_recent:]


def record_upload(state: dict, content_id: str, meta: dict) -> None:
    state["uploads"][content_id] = meta


def get_uploads(state: dict) -> dict:
    return state.get("uploads", {})


def mark_deleted(state: dict, content_id: str) -> None:
    state["uploads"].pop(content_id, None)


def find_upload_by_hash(state: dict, file_hash: str) -> tuple[str, dict] | None:
    for cid, meta in state.get("uploads", {}).items():
        if meta.get("file_hash") == file_hash:
            return cid, meta
    return None
