"""Subtitle source plugins: Addic7ed through Gestdown, and SubDL, against stand-ins for their APIs."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from cue.providers.base import Episode, Show
from cue.subtitles.base import SubtitleError, SubtitleTrack
from cue.subtitles.registry import create_sources, subtitle_backends, subtitle_origin
from cue_plugins.gestdown import Gestdown
from cue_plugins.subdl import SubDL

SHOW = Show("bb", "Breaking Bad - Season 1", series_title="Breaking Bad")
EPISODE = Episode("bb", 2, season=1)
MOVIE = Show("heat", "Heat", year=1995, media_type="movie")
SRT = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"


def client(respond, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(record))


def test_both_sources_register_when_their_plugins_load(tmp_path: Path) -> None:
    assert subtitle_origin("gestdown") == "plugin:gestdown" and subtitle_origin("subdl") == "plugin:subdl"
    assert subtitle_backends()["subdl"].missing({})[0].key == "api_key"  # SubDL needs a key; Gestdown doesn't
    sources, problems = create_sources({"subdl": {"api_key": "k"}}, httpx.AsyncClient(), tmp_path)
    assert {"gestdown", "subdl"} <= {source.name for source in sources} and "subdl" not in problems


# -- Gestdown (Addic7ed) --------------------------------------------------------------------


def gestdown_api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/shows/search/Breaking Bad":
        return httpx.Response(200, json={"shows": [{"id": "minis", "name": "Breaking Bad Minisodes"},
                                                   {"id": "show1", "name": "Breaking Bad"}]})
    if path.startswith("/shows/search/"):
        return httpx.Response(404, text="Couldn't find show")
    if path == "/subtitles/get/show1/1/2/en":
        return httpx.Response(200, json={"episode": {"season": 1, "number": 2}, "matchingSubtitles": [
            {"subtitleId": "hi", "version": "HDTV", "completed": True, "hearingImpaired": True,
             "downloadUri": "/subtitles/download/hi", "downloadCount": 900},
            {"subtitleId": "wip", "version": "WEB", "completed": False, "hearingImpaired": False,
             "downloadUri": "/subtitles/download/wip", "downloadCount": 999},
            {"subtitleId": "best", "version": "DVDRip", "completed": True, "hearingImpaired": False,
             "downloadUri": "/subtitles/download/best", "downloadCount": 10},
            {"subtitleId": "odd", "downloadUri": "https://elsewhere.test/x"},
        ]})
    if path == "/subtitles/get/show1/1/2/fr":
        return httpx.Response(404)
    if path == "/subtitles/get/show1/1/3/en":
        return httpx.Response(423)
    if path == "/subtitles/download/best":
        return httpx.Response(200, content=SRT, headers={"Content-Type": "text/srt"})
    return httpx.Response(500)


async def test_gestdown_finds_an_episode_by_title_season_and_number(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    source = Gestdown(client(gestdown_api, seen), tmp_path)
    tracks = await source.find(SHOW, EPISODE, ["en", "fr"])
    # Finished first, then without hearing-impaired notes, then the most downloaded; odd links skipped.
    assert [(t.id, t.label, t.language) for t in tracks] == [
        ("best", "DVDRip", "en"), ("hi", "HDTV · hearing impaired", "en"), ("wip", "WEB · unfinished", "en")]
    assert all(t.source == "gestdown" for t in tracks)
    assert all(request.headers["User-Agent"].startswith("cue/") for request in seen)

    await source.find(SHOW, EPISODE, ["en"])
    assert sum(request.url.path.startswith("/shows/search/") for request in seen) == 1  # the show is looked up once

    path = Path(await source.fetch(tracks[0]))
    assert path.read_bytes() == SRT and path == tmp_path / "gestdown" / "Breaking Bad - Season 1" / "2.en.best.srt"


async def test_gestdown_skips_what_addic7ed_doesnt_have(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    source = Gestdown(client(gestdown_api, seen), tmp_path)
    assert await source.find(MOVIE, Episode("heat", 1), ["en"]) == [] and seen == []  # TV only
    assert await source.find(SHOW, Episode("bb", 2.5, season=1), ["en"]) == []  # no specials
    assert await source.find(Show("x", "Unknown Show"), Episode("x", 1), ["en"]) == []
    with pytest.raises(SubtitleError, match="try again in a minute"):  # 423: Gestdown is busy fetching it
        await source.find(SHOW, Episode("bb", 3, season=1), ["en"])
    with pytest.raises(SubtitleError, match="Not a Gestdown subtitle"):  # only Gestdown's own links
        await source.fetch(SubtitleTrack("en", "x", url="https://evil.test/a.srt"))


# -- SubDL --------------------------------------------------------------------------------


def zipped(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


SEARCH = {"status": True, "results": [{"name": "Breaking Bad", "type": "tv"}], "subtitles": [
    {"release_name": "Breaking.Bad.S01E02.720p", "language": "EN", "url": "/subtitle/1-2.zip", "season": 1,
     "episode": 2, "author": "sam"},
    {"release_name": "Breaking.Bad.S01.Complete", "language": "EN", "url": "/subtitle/3-4.zip", "season": 1,
     "full_season": True},
    {"release_name": "Breaking.Bad.S01E02.HI", "language": "EN", "url": "/subtitle/5-6.zip", "season": 1,
     "episode": 2, "hi": True},
    {"release_name": "Breaking.Bad.S01E03", "language": "EN", "url": "/subtitle/7-8.zip", "season": 1, "episode": 3},
    {"release_name": "Breaking.Bad.S02E02", "language": "EN", "url": "/subtitle/9-9.zip", "season": 2, "episode": 2},
    {"release_name": "Breaking.Bad.S01E02.PT", "language": "BR_PT", "url": "/subtitle/10-1.zip", "season": 1,
     "episode": 2},
    {"release_name": "elsewhere", "language": "EN", "url": "https://evil.test/x.zip", "season": 1, "episode": 2},
]}
ZIPS = {
    "/subtitle/1-2.zip": zipped({"Breaking.Bad.S01E02.720p.srt": SRT, "readme.txt": b"thanks"}),
    "/subtitle/3-4.zip": zipped({"S01/Breaking.Bad.S01E01.srt": b"one", "S01/Breaking.Bad.S01E02.ass": b"two",
                                 "S01/Breaking.Bad.S01E03.srt": b"three"}),
    "/subtitle/5-6.zip": zipped({"notes.txt": b"no subtitles in here"}),
    "/subtitle/10-1.zip": b"not a zip",
}


def subdl_api(search: dict | None = None, status: int = 200):
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.subdl.com":
            return httpx.Response(status, json=search if search is not None else SEARCH)
        if request.url.host == "dl.subdl.com" and request.url.path in ZIPS:
            return httpx.Response(200, content=ZIPS[request.url.path])
        return httpx.Response(404)

    return respond


async def test_subdl_searches_by_title_season_and_episode(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    source = SubDL("my-key", client(subdl_api(), seen), tmp_path)
    tracks = await source.find(SHOW, EPISODE, ["en", "pt-br"])
    query = dict(seen[0].url.params)
    assert query == {"api_key": "my-key", "film_name": "Breaking Bad", "languages": "EN,BR_PT", "subs_per_page": "30",
                     "type": "tv", "season_number": "1", "episode_number": "2"}
    assert seen[0].headers["User-Agent"].startswith("cue/")
    # This episode only (and the season pack that has it), single episodes first, hearing-impaired after.
    assert [(t.language, t.id) for t in tracks] == [("en", "1-2"), ("pt-br", "10-1"), ("en", "5-6"), ("en", "3-4")]
    assert tracks[0].label == "Breaking.Bad.S01E02.720p · by sam" and tracks[3].label.endswith("whole season")
    assert {t.source for t in tracks} == {"subdl"}

    single = Path(await source.fetch(tracks[0]))
    assert single.read_bytes() == SRT
    assert single == tmp_path / "subdl" / "Breaking Bad - Season 1" / "2.en.1-2.srt"
    from_pack = Path(await source.fetch(tracks[3]))  # the whole season: just this episode's file
    assert from_pack.read_bytes() == b"two" and from_pack.suffix == ".ass"
    with pytest.raises(SubtitleError, match="no subtitle file"):
        await source.fetch(tracks[2])
    with pytest.raises(SubtitleError, match="wasn't a zip"):
        await source.fetch(tracks[1])

    episode_four = await source.find(SHOW, Episode("bb", 4, season=1), ["en"])
    assert [t.id for t in episode_four] == ["3-4"]  # only the season pack covers it, and it lacks E04
    with pytest.raises(SubtitleError, match="no file for episode 4"):
        await source.fetch(episode_four[0])


async def test_subdl_movies_and_problems(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    movie = SubDL("k", client(subdl_api({"status": True, "subtitles": [
        {"release_name": "Heat.1995", "language": "EN", "url": "/subtitle/1-2.zip"}]}), seen), tmp_path)
    tracks = await movie.find(MOVIE, Episode("heat", 1), ["en"])
    assert [t.id for t in tracks] == ["1-2"]
    assert dict(seen[0].url.params) == {"api_key": "k", "film_name": "Heat", "languages": "EN", "subs_per_page": "30",
                                        "type": "movie", "year": "1995"}
    assert Path(await movie.fetch(tracks[0])) == tmp_path / "subdl" / "Heat" / "en.1-2.srt"

    nothing = SubDL("k", client(subdl_api({"status": False, "error": "can't find movie or tv"}), []), tmp_path)
    assert await nothing.find(SHOW, EPISODE, ["en"]) == []
    for respond, message in (
        (subdl_api({"status": False, "error": "Not Authorized"}, status=403), "refused the API key"),
        (subdl_api({"status": False, "error": "server busy"}), "SubDL: server busy"),
        (subdl_api({}, status=429), "limit is reached"),
    ):
        with pytest.raises(SubtitleError, match=message):
            await SubDL("k", client(respond, []), tmp_path).find(SHOW, EPISODE, ["en"])
    assert await SubDL("k", client(subdl_api(), []), tmp_path).find(SHOW, Episode("bb", 2.5, season=1), ["en"]) == []
