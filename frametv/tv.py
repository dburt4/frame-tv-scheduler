from __future__ import annotations
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class TVWrapper:
    def __init__(self, config: dict) -> None:
        self._host: str = config["host"]
        self._port: int = config.get("port", 8001)
        self._token_file: str = config.get("token_file", "./data/tv_token.txt")
        self._timeout: float = config.get("connect_timeout", 10.0)
        self._art = None

    async def connect(self) -> bool:
        try:
            from samsungtvws.async_art import SamsungTVAsyncArt
            Path(self._token_file).parent.mkdir(parents=True, exist_ok=True)
            self._art = SamsungTVAsyncArt(
                host=self._host,
                port=self._port,
                token_file=self._token_file,
                timeout=self._timeout,
            )
            await self._art.open()
            supported = await self._art.supported()
            if not supported:
                log.warning("TV at %s does not support art mode", self._host)
                await self._art.close()
                self._art = None
                return False
            log.info("Connected to TV at %s", self._host)
            return True
        except Exception as e:
            log.warning("Could not connect to TV at %s: [%s] %s", self._host, type(e).__name__, e)
            self._art = None
            return False

    async def upload_and_select(self, local_path: Path) -> str | None:
        if not self._art:
            return None
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            # upload() returns the content_id assigned by the TV
            content_id = await self._art.upload(data)
            if content_id:
                await self._art.select_image(content_id, show=True)
            return content_id
        except Exception as e:
            log.warning("Upload/select failed: %s", e)
            return None

    async def select_existing(self, content_id: str) -> bool:
        if not self._art:
            return False
        try:
            await self._art.select_image(content_id, show=True)
            return True
        except Exception as e:
            log.warning("select_image(%s) failed: %s", content_id, e)
            return False

    async def delete(self, content_id: str) -> bool:
        if not self._art:
            return False
        try:
            await self._art.delete(content_id)
            return True
        except Exception as e:
            log.warning("delete(%s) failed: %s", content_id, e)
            return False

    async def get_current(self) -> str | None:
        if not self._art:
            return None
        try:
            info = await self._art.get_current()
            if isinstance(info, dict):
                return info.get("content_id")
            return None
        except Exception as e:
            log.warning("get_current() failed: %s", e)
            return None

    async def is_art_mode(self) -> bool:
        if not self._art:
            return False
        try:
            mode = await self._art.get_artmode()
            return mode == "on"
        except Exception as e:
            log.warning("get_artmode() failed: %s", e)
            return False

    async def close(self) -> None:
        if self._art:
            try:
                await self._art.close()
            except Exception:
                pass
            self._art = None
