import json
import os
import pytest
from pathlib import Path
from frametv import state as state_mod


def test_load_nonexistent_returns_empty(tmp_path):
    s = state_mod.load_state(tmp_path / "missing.json")
    assert s == {"schedules": {}, "uploads": {}}


def test_save_and_reload(tmp_path):
    p = tmp_path / "state.json"
    data = state_mod.load_state(p)
    state_mod.record_upload(data, "MY-123", {"source_name": "nasa", "source_key": "2025-01-01", "file_hash": "abc", "uploaded_at": "2025-01-01T00:00:00", "expires": True, "ttl_days": 7})
    state_mod.save_state(p, data)
    loaded = state_mod.load_state(p)
    assert "MY-123" in loaded["uploads"]
    assert loaded["uploads"]["MY-123"]["source_name"] == "nasa"


def test_atomic_write_uses_tmp(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    tmp_seen = []
    original_replace = os.replace
    def mock_replace(src, dst):
        tmp_seen.append(src)
        original_replace(src, dst)
    monkeypatch.setattr(os, "replace", mock_replace)
    state_mod.save_state(p, {"schedules": {}, "uploads": {}})
    assert any(str(t).endswith(".tmp") for t in tmp_seen)


def test_get_schedule_state_defaults(tmp_path):
    state = state_mod.load_state(tmp_path / "s.json")
    ss = state_mod.get_schedule_state(state, "my-rule")
    assert ss["last_change_at"] is None
    assert ss["last_index"] == 0
    assert ss["last_shown_key"] is None
    assert ss["recently_shown"] == []


def test_record_shown_tracks_keys(tmp_path):
    state = state_mod.load_state(tmp_path / "s.json")
    state_mod.record_shown(state, "default", "img1.jpg", "random", "default")
    state_mod.record_shown(state, "default", "img2.jpg", "random", "default")
    ss = state_mod.get_schedule_state(state, "default")
    assert "img1.jpg" in ss["recently_shown"]
    assert "img2.jpg" in ss["recently_shown"]
    assert ss["active_rule_name"] == "default"
    assert ss["last_change_at"] is not None
    assert ss["last_shown_key"] == "img2.jpg"


def test_record_shown_no_duplicates(tmp_path):
    state = state_mod.load_state(tmp_path / "s.json")
    state_mod.record_shown(state, "default", "img1.jpg", "random", "default")
    state_mod.record_shown(state, "default", "img1.jpg", "random", "default")
    ss = state_mod.get_schedule_state(state, "default")
    assert ss["recently_shown"].count("img1.jpg") == 1
    assert ss["last_shown_key"] == "img1.jpg"


def test_record_shown_respects_max_recent(tmp_path):
    state = state_mod.load_state(tmp_path / "s.json")
    for i in range(30):
        state_mod.record_shown(state, "default", f"img{i}.jpg", "random", "default", max_recent=10)
    ss = state_mod.get_schedule_state(state, "default")
    assert len(ss["recently_shown"]) <= 10


def test_mark_deleted_removes_entry():
    state = {"schedules": {}, "uploads": {"MY-123": {"expires": True}}}
    state_mod.mark_deleted(state, "MY-123")
    assert "MY-123" not in state["uploads"]
    # Idempotent
    state_mod.mark_deleted(state, "MY-123")


def test_find_upload_by_hash():
    state = {
        "schedules": {},
        "uploads": {
            "CID-1": {"file_hash": "abc123", "source_name": "nasa"},
            "CID-2": {"file_hash": "def456", "source_name": "local"},
        }
    }
    result = state_mod.find_upload_by_hash(state, "abc123")
    assert result is not None
    cid, meta = result
    assert cid == "CID-1"

    assert state_mod.find_upload_by_hash(state, "notexist") is None


def test_corrupt_state_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{{not valid json")
    s = state_mod.load_state(p)
    assert s == {"schedules": {}, "uploads": {}}
