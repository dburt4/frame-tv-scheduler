from __future__ import annotations
import logging
from datetime import datetime, timedelta
from frametv import state as state_mod
from frametv.tv import TVWrapper

log = logging.getLogger(__name__)


async def expire_old_uploads(state: dict, tv: TVWrapper, now: datetime) -> None:
    uploads = state_mod.get_uploads(state)
    to_delete = [
        (cid, meta) for cid, meta in uploads.items()
        if meta.get("expires")
        and _is_expired(meta, now)
    ]
    if not to_delete:
        return
    log.info("Expiring %d old API uploads from TV", len(to_delete))
    for content_id, meta in to_delete:
        success = await tv.delete(content_id)
        if success:
            state_mod.mark_deleted(state, content_id)
            log.info("Deleted expired upload %s (%s / %s)", content_id, meta.get("source_name"), meta.get("source_key"))
        else:
            log.warning("Failed to delete %s from TV; will retry next run", content_id)


def _is_expired(meta: dict, now: datetime) -> bool:
    uploaded_at_str = meta.get("uploaded_at")
    ttl_days = meta.get("ttl_days", 7)
    if not uploaded_at_str:
        return False
    try:
        uploaded_at = datetime.fromisoformat(uploaded_at_str)
        return now >= uploaded_at + timedelta(days=ttl_days)
    except (ValueError, TypeError):
        return False
