"""Optional Blink camera snapshot support.

Blink does not provide a LAN RTSP-style live stream through blinkpy. This
module exposes a cached JPEG snapshot and refreshes it no faster than once per
minute so the Progress page can show a live-ish view without hammering Blink's
cloud API.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .config import settings

MIN_REFRESH_SECONDS = 60


class BlinkCameraError(RuntimeError):
    """Raised when the optional Blink integration cannot return an image."""


@dataclass
class BlinkSnapshot:
    image: bytes
    camera_name: str
    refreshed_at: float


class BlinkCameraService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._blink = None
        self._snapshot: BlinkSnapshot | None = None
        self._last_error: str | None = None

    @property
    def refresh_seconds(self) -> int:
        return max(MIN_REFRESH_SECONDS, int(settings.blink_refresh_seconds or MIN_REFRESH_SECONDS))

    def status(self) -> dict:
        return {
            "enabled": settings.blink_enabled,
            "configured": bool(settings.blink_username and settings.blink_password),
            "camera_name": settings.blink_camera_name or None,
            "refresh_seconds": self.refresh_seconds,
            "has_snapshot": self._snapshot is not None,
            "refreshed_at": self._snapshot.refreshed_at if self._snapshot else None,
            "last_error": self._last_error,
        }

    async def get_snapshot(self) -> BlinkSnapshot:
        if not settings.blink_enabled:
            raise BlinkCameraError("Blink camera feed is disabled")
        if not settings.blink_username or not settings.blink_password:
            raise BlinkCameraError("Blink username/password are not configured")

        async with self._lock:
            now = time.time()
            if self._snapshot and now - self._snapshot.refreshed_at < self.refresh_seconds:
                return self._snapshot

            try:
                snapshot = await self._refresh_snapshot()
            except Exception as exc:  # Keep the Progress page usable on camera errors.
                self._last_error = str(exc)
                if self._snapshot:
                    return self._snapshot
                raise BlinkCameraError(str(exc)) from exc

            self._snapshot = snapshot
            self._last_error = None
            return snapshot

    async def _refresh_snapshot(self) -> BlinkSnapshot:
        blink = await self._get_blink()
        camera = self._select_camera(blink.cameras)

        snap_picture = getattr(camera, "snap_picture", None)
        if callable(snap_picture):
            await snap_picture()

        await blink.refresh()
        image = getattr(camera, "image_from_cache", None)
        if not image:
            await blink.refresh(force=True)
            image = getattr(camera, "image_from_cache", None)

        if not image:
            raise BlinkCameraError("No Blink camera snapshot is available yet")

        return BlinkSnapshot(bytes(image), getattr(camera, "name", settings.blink_camera_name), time.time())

    async def _get_blink(self):
        if self._blink is not None:
            return self._blink

        try:
            from aiohttp import ClientSession
            from blinkpy.auth import Auth
            from blinkpy.blinkpy import Blink
        except ImportError as exc:
            raise BlinkCameraError("blinkpy is not installed; run pip install -r requirements.txt") from exc

        session = ClientSession()
        blink = Blink(session=session)
        blink.auth = Auth(
            {
                "username": settings.blink_username,
                "password": settings.blink_password,
            },
            no_prompt=True,
        )
        await blink.start()
        self._blink = blink
        return blink

    def _select_camera(self, cameras: dict):
        if not cameras:
            raise BlinkCameraError("No Blink cameras were found on this account")

        if settings.blink_camera_name:
            camera = cameras.get(settings.blink_camera_name)
            if camera is None:
                names = ", ".join(sorted(cameras.keys()))
                raise BlinkCameraError(
                    f"Blink camera {settings.blink_camera_name!r} was not found. Available: {names}"
                )
            return camera

        return next(iter(cameras.values()))


blink_camera_service = BlinkCameraService()
