"""The ffplay and default-app player plugins."""

from __future__ import annotations

from pathlib import Path

import pytest

from cue.player.base import PlayerError
from cue.player.registry import player_origin, players


def test_ffplay_plugin_arguments_and_failures() -> None:
    from cue_plugins.ffplay import FfplayPlayer

    assert player_origin("ffplay") == "plugin:ffplay" and not players()["ffplay"].controls
    player = FfplayPlayer("ffplay", {"fullscreen": False})
    args = player.arguments("https://cdn.example/a.m3u8", start=61.25, title="Show",
                            headers={"Referer": "https://site.example/", "User-Agent": "UA"}, extra_args=["--fs"])
    assert args == [
        "-hide_banner", "-loglevel", "error", "-nostats", "-autoexit", "-window_title", "Show", "-ss", "61.250",
        "-headers", "Referer: https://site.example/\r\nUser-Agent: UA\r\n", "https://cdn.example/a.m3u8",
    ]
    assert "-fs" in FfplayPlayer("ffplay", {}).arguments("u", start=None, title=None, headers={}, extra_args=())
    # ffplay exits with 0 when it can't open a source, so a quick exit with an error printed is a failure.
    assert player.failure(0, ["Server returned 404 Not Found"], 0.6) == "Server returned 404 Not Found"
    assert player.failure(0, ["decode glitch"], 1200.0) is None
    assert player.failure(1, ["crashed"], 1200.0) == "crashed"


async def test_default_app_plugin_opens_local_files_only(tmp_path: Path) -> None:
    from cue_plugins.default_app import DefaultAppPlayer

    backend = players()["default-app"]
    assert player_origin("default-app") == "plugin:default-app" and not backend.has_program
    # It only opens files, so Cue downloads a streamed episode for it first.
    assert getattr(backend, "links", False) is False
    opened = []
    player = DefaultAppPlayer(opener=opened.append)
    media = tmp_path / "Episode 1.mkv"
    media.write_bytes(b"")
    await player.launch(str(media), headers=None)
    assert opened == [str(media)] and player.running
    await player.quit()
    assert not player.running
    # Only a Cue too old to download for it would hand it a link.
    with pytest.raises(PlayerError, match="can't download streams"):
        await DefaultAppPlayer(opener=opened.append).launch("https://cdn.example/a.m3u8")
    with pytest.raises(PlayerError, match="can't be controlled"):
        await player.command("seek", 1)
