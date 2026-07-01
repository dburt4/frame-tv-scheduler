from __future__ import annotations
import hashlib
import logging
import tempfile
from pathlib import Path
from frametv import state as state_mod
from frametv.sources.base import ArtItem, ArtSource
from frametv.tv import TVWrapper

log = logging.getLogger(__name__)

_MAX_PORTRAIT_RETRIES = 10
_TV_MAX_WIDTH = 3840
_TV_MAX_HEIGHT = 2160
_TV_MAX_BYTES = 8 * 1024 * 1024  # 8 MB


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_image(local_path: Path, portrait_handling: str) -> Path | None:
    """Resize/convert image for the Frame TV. Returns a temp JPEG path, or None if portrait and mode=skip."""
    from PIL import Image, ImageFilter

    img = Image.open(local_path)
    w, h = img.size

    is_portrait = h > w
    if is_portrait:
        if portrait_handling == "skip":
            return None
        if portrait_handling == "blur":
            img = _make_blur_composite(img)
            w, h = img.size

    # Convert to RGB (handles PNG/WebP with alpha)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Resize to fit within 3840x2160 preserving aspect ratio
    if w > _TV_MAX_WIDTH or h > _TV_MAX_HEIGHT:
        img.thumbnail((_TV_MAX_WIDTH, _TV_MAX_HEIGHT), Image.LANCZOS)

    # Save to temp JPEG
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    quality = 92
    img.save(tmp.name, "JPEG", quality=quality, optimize=True)
    # Reduce quality if over size limit
    while Path(tmp.name).stat().st_size > _TV_MAX_BYTES and quality > 60:
        quality -= 8
        img.save(tmp.name, "JPEG", quality=quality, optimize=True)

    return Path(tmp.name)


def _make_blur_composite(img):
    from PIL import Image, ImageFilter, ImageEnhance
    target_w, target_h = _TV_MAX_WIDTH, _TV_MAX_HEIGHT
    # Create blurred background scaled to fill 16:9
    bg = img.copy().convert("RGB")
    bg = bg.resize((target_w, target_h), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))
    bg = ImageEnhance.Brightness(bg).enhance(0.4)
    # Scale original to fit height
    orig = img.convert("RGBA")
    scale = target_h / orig.height
    new_w = int(orig.width * scale)
    orig = orig.resize((new_w, target_h), Image.LANCZOS)
    # Center paste
    x = (target_w - new_w) // 2
    bg.paste(orig, (x, 0), orig)
    return bg.convert("RGB")


async def _pick_next_item(
    source: ArtSource,
    exclude_keys: list[str],
    last_index: int,
    mode: str,
    current_key: str | None,
) -> tuple[ArtItem | None, int]:
    item, new_index = await source.get_next(exclude_keys, last_index, mode)
    if item is None or mode != "random" or not current_key or item.key != current_key:
        return item, new_index

    log.debug("Random selection matched current image %s; picking again", current_key)
    retry_item, retry_index = await source.get_next(exclude_keys + [item.key], last_index, mode)
    if retry_item is not None:
        return retry_item, retry_index
    return item, new_index


async def rotate_art(
    active_rule: dict,
    source: ArtSource,
    tv: TVWrapper,
    state: dict,
    source_config: dict,
) -> bool:
    schedule_name = active_rule["name"]
    mode = active_rule.get("mode", "random")
    portrait_handling = source_config.get("portrait_handling", "skip")
    expires = source_config.get("expires", False)
    ttl_days = source_config.get("ttl_days", 7)

    sched_state = state_mod.get_schedule_state(state, schedule_name)
    exclude_keys: list[str] = sched_state.get("recently_shown", [])
    last_index: int = sched_state.get("last_index", 0)

    current_key: str | None = sched_state.get("last_shown_key")

    for attempt in range(_MAX_PORTRAIT_RETRIES):
        item, new_index = await _pick_next_item(
            source, exclude_keys, last_index, mode, current_key,
        )
        if item is None:
            log.warning("Source returned no item for rule '%s'", schedule_name)
            return False

        if item.local_path is None:
            log.warning("Item %s: download failed, skipping (attempt %d)", item.key, attempt + 1)
            exclude_keys = exclude_keys + [item.key]
            last_index = new_index
            continue

        prepared = prepare_image(item.local_path, portrait_handling)
        if prepared is None:
            log.debug("Skipping portrait image %s (attempt %d)", item.key, attempt + 1)
            exclude_keys = exclude_keys + [item.key]
            last_index = new_index
            continue

        # Dedup: check if this exact file was already uploaded
        try:
            fhash = _file_hash(prepared)
        except OSError as e:
            log.warning("Could not hash %s: %s", prepared, e)
            prepared.unlink(missing_ok=True)
            return False

        existing = state_mod.find_upload_by_hash(state, fhash)
        if existing:
            content_id, meta = existing
            log.info("Reusing existing upload %s for item %s", content_id, item.key)
            ok = await tv.select_existing(content_id)
        else:
            log.info("Uploading %s (%s)", item.key, item.title or "untitled")
            content_id = await tv.upload_and_select(prepared)
            if not content_id:
                log.warning("Upload failed for item %s", item.key)
                prepared.unlink(missing_ok=True)
                return False
            ok = True
            state_mod.record_upload(state, content_id, {
                "source_name": active_rule["source"],
                "source_key": item.key,
                "file_hash": fhash,
                "uploaded_at": __import__("datetime").datetime.now().isoformat(),
                "expires": expires,
                "ttl_days": ttl_days,
            })

        prepared.unlink(missing_ok=True)

        if ok:
            sched_state["last_index"] = new_index
            state_mod.record_shown(state, schedule_name, item.key, mode, active_rule["name"])
            log.info("Now displaying: %s — %s", item.key, item.title or "untitled")
            return True
        return False

    log.warning("Exhausted %d retries for rule '%s' (all portrait?)", _MAX_PORTRAIT_RETRIES, schedule_name)
    return False
