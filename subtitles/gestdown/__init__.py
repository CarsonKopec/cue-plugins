"""Subtitles for TV shows from Addic7ed, through Gestdown (https://www.gestdown.info).

Gestdown's API finds a show by title, then an episode's subtitles by season, episode
and language (ISO codes such as ``en``). It needs no account or key. Addic7ed has TV
shows only, so movies get nothing here. Files are kept under
``<subtitles folder>/gestdown/<show>/``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from cue import __version__
from cue.providers.base import Episode, Show
from cue.subtitles.base import SubtitleError, SubtitleTrack
from cue.subtitles.registry import SubtitleBackend, register_subtitles
from cue.util import safe_filename

NAME = "gestdown"
API = "https://api.gestdown.info"
HEADERS = {"User-Agent": f"cue/{__version__} (+https://github.com/CarsonKopec/Cue)", "Accept": "application/json"}
TIMEOUT = 20.0
MAX_FILE_BYTES = 5 * 1024 * 1024


class Gestdown:
    name = NAME

    def __init__(self, http: httpx.AsyncClient, folder: Path) -> None:
        self._http = http
        self._folder = folder / NAME
        self._shows: dict[str, str | None] = {}  # title -> Gestdown's show id (None: not on Addic7ed)
        self._targets: dict[str, Path] = {}

    async def find(
        self, show: Show, episode: Episode, languages: list[str], *, file_path: str | None = None,
    ) -> list[SubtitleTrack]:
        if show.media_type == "movie" or not float(episode.number).is_integer():
            return []  # Addic7ed has TV episodes only
        show_id = await self._show_id(show.series_title or show.title)
        if show_id is None:
            return []
        season, number = episode.season or 1, int(episode.number)
        tracks: list[SubtitleTrack] = []
        for language in dict.fromkeys(languages):
            data = await self._json(f"/subtitles/get/{quote(show_id)}/{season}/{number}/{quote(language)}")
            matches = data.get("matchingSubtitles") if isinstance(data, dict) else None
            for item in sorted((m for m in matches or [] if isinstance(m, dict)), key=_rank):
                uri, subtitle_id = item.get("downloadUri"), item.get("subtitleId")
                if not isinstance(uri, str) or not uri.startswith("/subtitles/download/") or not subtitle_id:
                    continue
                track = SubtitleTrack(language, _label(item), url=API + uri, source=NAME, id=str(subtitle_id))
                self._targets[track.id] = (
                    self._folder / safe_filename(show.title) / f"{episode.label}.{language}.{track.id}.srt")
                tracks.append(track)
        return tracks

    async def fetch(self, track: SubtitleTrack) -> str:
        if not track.url or not track.url.startswith(f"{API}/subtitles/download/"):
            raise SubtitleError("Not a Gestdown subtitle")
        response = await self._get(track.url)
        if response.status_code != 200:
            raise SubtitleError(f"Gestdown couldn't send that subtitle (HTTP {response.status_code})")
        if len(response.content) > MAX_FILE_BYTES:
            raise SubtitleError("Gestdown sent a file far too large to be a subtitle")
        target = self._targets.get(track.id) or self._folder / f"{track.id}.srt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(response.content)
        return str(target)

    async def _show_id(self, title: str) -> str | None:
        if title not in self._shows:
            data = await self._json(f"/shows/search/{quote(title, safe='')}")
            shows = [s for s in (data.get("shows") or []) if isinstance(s, dict) and s.get("id")] if isinstance(
                data, dict) else []
            wanted = _plain(title)
            best = next((s for s in shows if _plain(str(s.get("name", ""))) == wanted), shows[0] if shows else None)
            self._shows[title] = str(best["id"]) if best else None
        return self._shows[title]

    async def _get(self, url: str) -> httpx.Response:
        try:
            return await self._http.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise SubtitleError(f"Gestdown didn't answer ({type(exc).__name__})") from exc

    async def _json(self, path: str) -> Any:
        """The answer to ``path``, or None when Gestdown has nothing there (404)."""
        response = await self._get(API + path)
        if response.status_code == 404:
            return None
        if response.status_code == 423:
            raise SubtitleError("Gestdown is still collecting this episode's subtitles; try again in a minute")
        if response.status_code == 429:
            raise SubtitleError("Gestdown asked Cue to slow down; try again in a little while")
        if response.status_code != 200:
            raise SubtitleError(f"Gestdown answered HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise SubtitleError("Gestdown's answer wasn't JSON") from exc


def _plain(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _rank(item: Mapping[str, Any]) -> tuple[bool, bool, int]:
    """Finished translations first, then without hearing-impaired notes, then the most downloaded."""
    downloads = item.get("downloadCount")
    return (not item.get("completed", True), bool(item.get("hearingImpaired")),
            -(downloads if isinstance(downloads, int) else 0))


def _label(item: Mapping[str, Any]) -> str:
    parts = [str(item.get("version") or "").strip() or "Addic7ed"]
    if item.get("hearingImpaired"):
        parts.append("hearing impaired")
    if not item.get("completed", True):
        parts.append("unfinished")
    return " · ".join(parts)


register_subtitles(SubtitleBackend(
    NAME, "Addic7ed (Gestdown)", lambda options, http, folder: Gestdown(http, folder),
    description="TV shows from Addic7ed, through Gestdown. No account or key needed; movies aren't covered.",
    homepage="https://www.gestdown.info",
))
