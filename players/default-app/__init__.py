"""Open files in the operating system's default app for their type.

Windows uses the app set in Settings → Default apps (Media Player, Movies & TV, …),
macOS uses ``open`` (QuickTime, IINA, …) and Linux ``xdg-open``. Those apps can't open
a stream's link (Windows would hand it to a web browser), so this player says it only
opens files (``links=False``) and Cue downloads each streamed episode for it first.
Cue hands the file over and steps back, so press q in Cue when you're done.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cue.player.base import PlayerError
from cue.player.registry import PlayerBackend, register_player
from cue.providers.base import is_local_file


def _open(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opening the user's own file is the point
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(["xdg-open", path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


class DefaultAppPlayer:
    title = "Your default app"

    def __init__(self, options: Mapping[str, Any] | None = None, opener: Callable[[str], None] = _open) -> None:
        self._opener = opener
        self._open = False
        self._close_callbacks: list[Callable[[], None]] = []

    @property
    def running(self) -> bool:
        return self._open

    def observe(self, name: str, callback: Callable[[Any], None]) -> None:
        pass  # the other app reports nothing back

    def on_close(self, callback: Callable[[], None]) -> None:
        self._close_callbacks.append(callback)

    async def launch(
        self, url: str, *, start: float | None = None, headers: Mapping[str, str] | None = None,
        title: str | None = None, extra_args: Sequence[str] = (),
    ) -> None:
        if not is_local_file(url):  # only on a Cue too old to download streams for it
            raise PlayerError("This Cue can't download streams for the default app; update Cue, or pick VLC or mpv.")
        try:
            self._opener(url)
        except OSError as exc:
            raise PlayerError(f"Could not open the file: {exc.strerror or exc}") from exc
        self._open = True

    async def command(self, *args: Any, timeout: float = 5.0) -> Any:
        raise PlayerError("The default app can't be controlled from Cue")

    async def quit(self, timeout: float = 3.0) -> None:
        self._open = False  # the other app stays open; Cue just stops waiting for it

    def kill(self) -> None:
        self._open = False


# Cue 0.4 and newer download a streamed episode for players that only open files.
_FILES_ONLY = {"links": False} if "links" in getattr(PlayerBackend, "__dataclass_fields__", {}) else {}

register_player(PlayerBackend(
    name="default-app",
    title="Default app",
    locate=lambda options: "your system's default app for each file type",
    create=lambda program, options: DefaultAppPlayer(options),
    description="Opens episodes in your default video app, such as Windows' Media Player. A streamed episode "
                "is downloaded first (needs FFmpeg or yt-dlp). Cue can't skip intros or save your place in it.",
    controls=False,
    has_program=False,
    **_FILES_ONLY,
))
