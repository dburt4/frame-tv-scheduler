import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from frametv.sources.base import ArtItem
from frametv.uploader import prepare_image, _pick_next_item, rotate_art


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def landscape_jpg(tmp_path):
    """Create a valid 1920x1080 landscape JPEG."""
    from PIL import Image
    img = Image.new("RGB", (1920, 1080), color=(100, 150, 200))
    p = tmp_path / "landscape.jpg"
    img.save(p, "JPEG")
    return p


@pytest.fixture
def portrait_jpg(tmp_path):
    """Create a valid 1080x1920 portrait JPEG."""
    from PIL import Image
    img = Image.new("RGB", (1080, 1920), color=(200, 100, 50))
    p = tmp_path / "portrait.jpg"
    img.save(p, "JPEG")
    return p


def test_landscape_passes_through(landscape_jpg):
    result = prepare_image(landscape_jpg, "skip")
    assert result is not None
    assert result.exists()
    result.unlink()


def test_portrait_skip_returns_none(portrait_jpg):
    result = prepare_image(portrait_jpg, "skip")
    assert result is None


def test_portrait_blur_returns_landscape(portrait_jpg):
    result = prepare_image(portrait_jpg, "blur")
    assert result is not None
    from PIL import Image
    img = Image.open(result)
    w, h = img.size
    assert w > h, f"Expected landscape output, got {w}x{h}"
    result.unlink()


def test_large_image_is_resized(tmp_path):
    from PIL import Image
    # Create an image larger than 3840x2160
    img = Image.new("RGB", (5000, 3000), color=(50, 50, 50))
    p = tmp_path / "big.jpg"
    img.save(p, "JPEG")
    result = prepare_image(p, "skip")
    assert result is not None
    resized = Image.open(result)
    w, h = resized.size
    assert w <= 3840 and h <= 2160
    result.unlink()


def test_png_with_alpha_converted_to_jpeg(tmp_path):
    from PIL import Image
    img = Image.new("RGBA", (800, 600), color=(100, 150, 200, 128))
    p = tmp_path / "alpha.png"
    img.save(p, "PNG")
    result = prepare_image(p, "skip")
    assert result is not None
    assert result.suffix == ".jpg"
    from PIL import Image as PIL_Image
    out = PIL_Image.open(result)
    assert out.mode == "RGB"
    result.unlink()


@pytest.mark.parametrize("mode,current_key,first_key,second_key,expected_calls", [
    ("random", "a.jpg", "a.jpg", "b.jpg", 2),
    ("random", "a.jpg", "b.jpg", None, 1),
    ("random", None, "a.jpg", None, 1),
    ("sequential", "a.jpg", "a.jpg", None, 1),
])
def test_pick_next_item_random_retry(mode, current_key, first_key, second_key, expected_calls, tmp_path):
    async def _test():
        items = {
            "a.jpg": ArtItem(key="a.jpg", local_path=tmp_path / "a.jpg", title="A"),
            "b.jpg": ArtItem(key="b.jpg", local_path=tmp_path / "b.jpg", title="B"),
        }
        source = AsyncMock()
        if expected_calls == 2:
            source.get_next = AsyncMock(side_effect=[
                (items[first_key], 0),
                (items[second_key], 0),
            ])
        else:
            source.get_next = AsyncMock(return_value=(items[first_key], 0))

        item, idx = await _pick_next_item(source, [], 0, mode, current_key)
        assert item.key == (second_key or first_key)
        assert source.get_next.await_count == expected_calls
        if expected_calls == 2:
            source.get_next.assert_any_await([], 0, mode)
            source.get_next.assert_any_await([first_key], 0, mode)

    run(_test())


def test_pick_next_item_single_image_keeps_same_after_retry(tmp_path):
    async def _test():
        item = ArtItem(key="only.jpg", local_path=tmp_path / "only.jpg", title="Only")
        source = AsyncMock()
        source.get_next = AsyncMock(return_value=(item, 0))

        picked, _ = await _pick_next_item(source, [], 0, "random", "only.jpg")
        assert picked.key == "only.jpg"
        assert source.get_next.await_count == 2
        source.get_next.assert_any_await(["only.jpg"], 0, "random")

    run(_test())


def test_rotate_art_random_retries_before_upload(landscape_jpg, tmp_path):
    async def _test():
        other = tmp_path / "other.jpg"
        from PIL import Image
        Image.new("RGB", (1920, 1080), color=(10, 20, 30)).save(other, "JPEG")

        current = ArtItem(key=str(landscape_jpg), local_path=landscape_jpg, title="Current")
        replacement = ArtItem(key=str(other), local_path=other, title="Other")
        source = AsyncMock()
        source.get_next = AsyncMock(side_effect=[(current, 0), (replacement, 0)])

        tv = AsyncMock()
        tv.upload_and_select = AsyncMock(return_value="CID-NEW")
        tv.select_existing = AsyncMock(return_value=True)

        state = {
            "schedules": {
                "default": {
                    "last_shown_key": str(landscape_jpg),
                    "recently_shown": [str(landscape_jpg)],
                    "last_index": 0,
                }
            },
            "uploads": {},
        }

        ok = await rotate_art(
            {"name": "default", "source": "local", "mode": "random"},
            source,
            tv,
            state,
            {"portrait_handling": "skip", "expires": False},
        )
        assert ok is True
        assert source.get_next.await_count == 2
        tv.upload_and_select.assert_awaited_once()
        assert state["schedules"]["default"]["last_shown_key"] == str(other)

    run(_test())
