import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from frametv.uploader import prepare_image


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
