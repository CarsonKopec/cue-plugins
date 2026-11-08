"""Subtitles for movies and TV from SubDL (https://subdl.com), in many languages.

SubDL's API needs a free key: sign in at subdl.com and copy it from your profile. Cue
searches by title, season and episode (``api.subdl.com/api/v1/subtitles``), and each
subtitle comes as a zip from ``dl.subdl.com``. A whole-season zip gives up only the
episode being watched. Files are kept under ``<subtitles folder>/subdl/<show>/``.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from cue import __version__
from cue.providers.base import Episode, Setting, Show
from cue.subtitles.base import SubtitleError, SubtitleTrack
from cue.subtitles.registry import SubtitleBackend, register_subtitles
from cue.util import safe_filename

NAME = "subdl"
API = "https://api.subdl.com/api/v1/subtitles"
DOWNLOADS = "https://dl.subdl.com"
HEADERS = {"User-Agent": f"cue/{__version__} (+https://github.com/CarsonKopec/Cue)"}
TIMEOUT = 20.0
MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
SUBTITLE_FILES = (".srt", ".ass", ".ssa", ".vtt")
# SubDL's language codes are ISO 639-1 in capitals, except these.
_TO_SUBDL = {"pt-br": "BR_PT", "pb": "BR_PT", "zh-tw": "ZH_BG", "zh-hant": "ZH_BG"}
_FROM_SUBDL = {"BR_PT": "pt", "ZH_BG": "zh"}
_NOTHING = ("can't find", "cant find", "not found", "no subtitle")  # how SubDL says there's no match


@dataclass(frozen=True)
class _Wanted:
    season: int | None
    number: int | None
    target: Path  # without its extension; the file inside the zip decides it


class SubDL:
    name = NAME

    def __init__(self, api_key: str, http: httpx.AsyncClient, folder: Path) -> None:
        self._key = api_key
        self._http = http
        self._folder = folder / NAME
        self._wanted: dict[str, _Wanted] = {}

    async def find(
        self, show: Show, episode: Episode, languages: list[str], *, file_path: str | None = None,
    ) -> list[SubtitleTrack]:
        codes = {_code(language): language for language in languages}
        params: dict[str, Any] = {
            "api_key": self._key, "film_name": show.series_title or show.title,
            "languages": ",".join(codes), "subs_per_page": 30,
        }
        movie = show.media_type == "movie"
        if movie:
            params["type"] = "movie"
            if show.year:
                params["year"] = show.year
        else:
            if not float(episode.number).is_integer():
                return []  # SubDL numbers episodes 1, 2, ...; no specials like 12.5
            params.update(type="tv", season_number=episode.season or 1, episode_number=int(episode.number))
        season, number = (None, None) if movie else (episode.season or 1, int(episode.number))

        tracks: list[tuple[tuple[bool, bool], SubtitleTrack]] = []
        for item in await self._search(params):
            url = item.get("url")
            if not isinstance(url, str) or not re.fullmatch(r"/subtitle/[\w.-]+\.zip", url):
                continue
            code = str(item.get("language") or "").upper()
            language = codes.get(code) or _FROM_SUBDL.get(code) or code.lower()
            if language not in languages or (not movie and not _same_episode(item, season, number)):
                continue
            track = SubtitleTrack(language, _label(item), url=DOWNLOADS + url, source=NAME,
                                  id=PurePosixPath(url).stem)
            self._wanted[track.id] = _Wanted(season, number, self._folder / safe_filename(show.title) / (
                f"{episode.label}.{language}.{track.id}" if not movie else f"{language}.{track.id}"))
            tracks.append(((bool(item.get("full_season")), bool(item.get("hi"))), track))
        # SubDL's order otherwise; single episodes before season packs, then without hearing-impaired notes.
        return [track for _, track in sorted(tracks, key=lambda pair: pair[0])]

    async def fetch(self, track: SubtitleTrack) -> str:
        if not track.url or not track.url.startswith(f"{DOWNLOADS}/subtitle/"):
            raise SubtitleError("Not a SubDL subtitle")
        response = await self._get(track.url)
        if response.status_code != 200:
            raise SubtitleError(f"SubDL couldn't send that subtitle (HTTP {response.status_code})")
        if len(response.content) > MAX_ZIP_BYTES:
            raise SubtitleError("SubDL sent a file far too large to be a subtitle")
        wanted = self._wanted.get(track.id) or _Wanted(None, None, self._folder / track.id)
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
                member = _pick(bundle, wanted)
                with bundle.open(member) as source:
                    data = source.read(MAX_FILE_BYTES + 1)
        except zipfile.BadZipFile as exc:
            raise SubtitleError("SubDL's download wasn't a zip") from exc
        if len(data) > MAX_FILE_BYTES:
            raise SubtitleError("SubDL's subtitle is far too large")
        target = wanted.target.with_name(wanted.target.name + PurePosixPath(member.filename).suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    async def _search(self, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        response = await self._get(API, params=params)
        if response.status_code in (401, 403):
            raise SubtitleError("SubDL refused the API key; check it in Plugins -> Subtitles")
        if response.status_code == 429:
            raise SubtitleError("SubDL's limit is reached for now; try again later")
        try:
            data = response.json()
        except ValueError as exc:
            raise SubtitleError(f"SubDL answered HTTP {response.status_code}") from exc
        if not isinstance(data, dict):
            raise SubtitleError("SubDL's answer was unexpected")
        if not data.get("status"):
            message = str(data.get("error") or data.get("message") or f"HTTP {response.status_code}")
            if any(words in message.lower() for words in _NOTHING):
                return []
            raise SubtitleError(f"SubDL: {message}")
        return [item for item in data.get("subtitles") or [] if isinstance(item, dict)]

    async def _get(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        try:
            return await self._http.get(url, params=params, headers=HEADERS, timeout=TIMEOUT, follow_redirects=False)
        except httpx.HTTPError as exc:
            raise SubtitleError(f"SubDL didn't answer ({type(exc).__name__})") from exc


def _code(language: str) -> str:
    """SubDL's code for an ISO 639-1 language (``en`` -> ``EN``, ``pt-br`` -> ``BR_PT``)."""
    language = language.lower()
    return _TO_SUBDL.get(language, language.split("-")[0].upper())


def _number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _same_episode(item: Mapping[str, Any], season: int | None, number: int | None) -> bool:
    """Whether a result is for this episode, or a whole-season pack that has it."""
    item_season = _number(item.get("season"))
    if item_season not in (None, 0) and item_season != season:
        return False
    if item.get("full_season"):
        return True
    first, last = _number(item.get("episode_from")), _number(item.get("episode_end"))
    if first and last:
        return number is not None and first <= number <= last
    episode = _number(item.get("episode"))
    return episode in (None, 0) or episode == number


def _label(item: Mapping[str, Any]) -> str:
    parts = [str(item.get("release_name") or item.get("name") or "SubDL").strip()]
    if item.get("hi"):
        parts.append("hearing impaired")
    if item.get("full_season"):
        parts.append("whole season")
    if item.get("author"):
        parts.append(f"by {item['author']}")
    return " · ".join(parts)


def _pick(bundle: zipfile.ZipFile, wanted: _Wanted) -> zipfile.ZipInfo:
    """The subtitle file in a zip: the only one, or this episode's from a season pack."""
    files = [info for info in bundle.infolist()
             if not info.is_dir() and PurePosixPath(info.filename).suffix.lower() in SUBTITLE_FILES
             and not PurePosixPath(info.filename).name.startswith(".")]
    if not files:
        raise SubtitleError("SubDL's zip has no subtitle file in it")
    if len(files) == 1 or wanted.number is None:
        return files[0]
    season, number = wanted.season or 1, wanted.number
    patterns = (
        rf"s0*{season}[ ._-]*e0*{number}(?!\d)",  # S01E02
        rf"(?<!\d)0*{season}x0*{number}(?!\d)",  # 1x02
        rf"(?:^|[^a-z])(?:e|ep|episode)[ ._-]*0*{number}(?!\d)",  # E02, Episode 2
    )
    for pattern in patterns:
        for info in files:
            if re.search(pattern, PurePosixPath(info.filename).name, re.IGNORECASE):
                return info
    raise SubtitleError(f"SubDL's season pack has no file for episode {number}")


register_subtitles(SubtitleBackend(
    NAME, "SubDL",
    lambda options, http, folder: SubDL(str(options["api_key"]).strip(), http, folder),
    description="Movies and TV in many languages. Needs a free API key from your subdl.com account.",
    settings=(Setting("api_key", "API key", "secret", required=True,
                      help="Free: sign in at subdl.com, open your profile, and copy the key from its API section."),),
    homepage="https://subdl.com",
))
