"""Open files in the operating system's default app for their type.

Windows uses the app set in Settings → Default apps (Media Player, Movies & TV, …),
macOS uses ``open`` (QuickTime, IINA, …) and Linux ``xdg-open``. Only files on this
PC are opened: a streaming link would land in a web browser, which can't play it.
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
        if not is_local_file(url):
            raise PlayerError("The default app plays files on this PC only; pick VLC or mpv for streams.")
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


register_player(PlayerBackend(
    name="default-app",
    title="Default app",
    locate=lambda options: "your system's default app for each file type",
    create=lambda program, options: DefaultAppPlayer(options),
    description="Opens files on this PC (the Local provider and downloads) in your default video app. "
                "Streams need VLC or mpv. Cue can't skip intros or save your place in it.",
    controls=False,
    has_program=False,
))
