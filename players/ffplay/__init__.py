"""ffplay, FFmpeg's small player, as a Cue player.

Cue starts ffplay at the resume point with the stream's headers and a window title.
ffplay has no remote control, so Cue can't follow its position, skip intros or
switch subtitles; closing its window (or q in ffplay) ends playback in Cue.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from cue.player.locate import beside_app
from cue.player.process import ProcessPlayer
from cue.player.registry import PlayerBackend, register_player
from cue.providers.base import Setting

EXECUTABLE = "ffplay.exe" if sys.platform == "win32" else "ffplay"
QUICK_EXIT = 5.0  # seconds; an exit this soon with an error printed means it never played


class FfplayPlayer(ProcessPlayer):
    title = "ffplay"
    headers = None  # ffplay's -headers option sends any header

    def arguments(
        self, url: str, *, start: float | None, headers: Mapping[str, str], title: str | None,
        extra_args: Sequence[str],
    ) -> list[str]:
        # extra_args (Cue's player_args) are written for VLC and mpv, so they aren't passed on.
        args = ["-hide_banner", "-loglevel", "error", "-nostats", "-autoexit"]
        if self.options.get("fullscreen", True):
            args.append("-fs")
        if title:
            args += ["-window_title", title]
        if start:
            args += ["-ss", f"{start:.3f}"]
        if headers:
            args += ["-headers", "".join(f"{name}: {value}\r\n" for name, value in headers.items())]
        return [*args, url]

    def failure(self, code: int, lines: list[str], seconds: float) -> str | None:
        # ffplay exits with 0 even when it can't open the source; it only prints why.
        return lines[-1] if lines and (code != 0 or seconds < QUICK_EXIT) else None


def _locate(options: Mapping[str, Any]) -> str | None:
    return beside_app(EXECUTABLE) or shutil.which(EXECUTABLE)


register_player(PlayerBackend(
    name="ffplay",
    title="ffplay",
    locate=_locate,
    create=lambda program, options: FfplayPlayer(program, options),
    missing="Install FFmpeg (ffmpeg.org) so ffplay is on PATH, or set its path here.",
    description="FFmpeg's small player: starts at your resume point and sends any header a source needs. "
                "Cue can't skip intros or save your place in it.",
    controls=False,
    settings=(Setting("fullscreen", "Full screen", "bool", True),),
))
