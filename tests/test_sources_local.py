import asyncio
import pytest
from pathlib import Path
from frametv.sources.local import LocalFolderSource


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def image_folder(tmp_path):
    """Create a temporary folder with 5 fake image files."""
    for name in ["alpha.jpg", "beta.jpg", "gamma.jpg", "delta.jpg", "epsilon.jpg"]:
        (tmp_path / name).write_bytes(b"fake")
    return tmp_path


def test_sequential_cycles_in_order(image_folder):
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": [str(image_folder)], "recursive": False, "extensions": ["jpg"]})
        assert len(src._items) == 5
        keys = []
        idx = 0
        for _ in range(5):
            item, idx = await src.get_next([], idx, "sequential")
            assert item is not None
            keys.append(item.key)
        # Should be alphabetical (alpha, beta, delta, epsilon, gamma)
        assert keys == sorted(keys, key=lambda k: Path(k).name.lower())
    run(_test())


def test_sequential_wraps_around(image_folder):
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": [str(image_folder)], "recursive": False, "extensions": ["jpg"]})
        n = len(src._items)
        idx = 0
        first_keys = []
        for _ in range(n):
            item, idx = await src.get_next([], idx, "sequential")
            first_keys.append(item.key)
        second_keys = []
        for _ in range(n):
            item, idx = await src.get_next([], idx, "sequential")
            second_keys.append(item.key)
        assert first_keys == second_keys
    run(_test())


def test_random_excludes_recently_shown(image_folder):
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": [str(image_folder)], "recursive": False, "extensions": ["jpg"]})
        all_keys = [it.key for it in src._items]
        exclude = all_keys[:-1]
        item, _ = await src.get_next(exclude, 0, "random")
        assert item is not None
        assert item.key == all_keys[-1]
    run(_test())


def test_random_resets_when_all_excluded(image_folder):
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": [str(image_folder)], "recursive": False, "extensions": ["jpg"]})
        all_keys = [it.key for it in src._items]
        item, _ = await src.get_next(all_keys, 0, "random")
        assert item is not None
    run(_test())


def test_empty_folder_returns_none(tmp_path):
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": [str(tmp_path)], "recursive": False, "extensions": ["jpg"]})
        item, idx = await src.get_next([], 0, "random")
        assert item is None
        assert idx == 0
    run(_test())


def test_nonexistent_path_is_skipped():
    async def _test():
        src = LocalFolderSource()
        await src.initialize({"paths": ["/nonexistent/path/xyz"], "recursive": False})
        item, _ = await src.get_next([], 0, "random")
        assert item is None
    run(_test())


def test_filters_by_extension(tmp_path):
    async def _test():
        (tmp_path / "photo.jpg").write_bytes(b"fake")
        (tmp_path / "document.pdf").write_bytes(b"fake")
        (tmp_path / "image.png").write_bytes(b"fake")
        src = LocalFolderSource()
        await src.initialize({"paths": [str(tmp_path)], "recursive": False, "extensions": ["jpg"]})
        assert len(src._items) == 1
        assert src._items[0].local_path.name == "photo.jpg"
    run(_test())
