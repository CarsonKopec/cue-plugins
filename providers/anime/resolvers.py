"""Small, data-only resolvers for the server pages HiAnime actually advertises.

Zoko's public player version 23 publishes a JSON ``window.__P`` envelope using
base64 and the fixed byte mask in https://zokoanime.video/core/obfuscate.js?v=23.
https://zokoanime.video/player.js?v=23 passes the decoded object to
https://zokoanime.video/core/index.js?v=23, which plays its ``src`` as HLS.
This module implements that published serialization, not JavaScript execution,
authentication, DRM, inferred API calls, or the player's edge-host failover.

MegaPlay supports only explicit video/source elements or JSON media sources.
Its observed Error Code 410 page is a removed-content error, not a stream.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from cue.providers.base import ProviderError, Stream
from cue.providers.web import (
    CHALLENGE, MediaHTML, fetch_page, http_url, json_scripts, streams_from_payload, valid_headers,
)

__all__ = ["resolve_server", "streams_from_payload"]

_HOSTS = {"zokoanime.video", "megaplay.buzz"}
_ZOKO_MASK = b"otaku-embed-v1"


def _zoko_payload(scripts: list[str]) -> Any | None:
    for script in scripts:
        match = re.search(r"\bwindow\.__P\s*=\s*([\"'])([A-Za-z0-9+/=]+)\1\s*;?", script)
        if match is None:
            continue
        try:
            encoded = base64.b64decode(match.group(2), validate=True)
            decoded = bytes(value ^ _ZOKO_MASK[index % len(_ZOKO_MASK)] for index, value in enumerate(encoded))
            payload = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise ProviderError("ZokoAnime's published player payload format has changed or is invalid") from exc
        if not isinstance(payload, dict):
            raise ProviderError("ZokoAnime returned an unsupported player payload")
        return payload
    return None


async def resolve_server(
    client: httpx.AsyncClient,
    url: str,
    *,
    referer: str,
    user_agent: str,
) -> list[Stream]:
    """Resolve an allowlisted embed through its normal public source data."""
    valid_url = http_url(url, url)
    if valid_url is None or urlsplit(valid_url).hostname not in _HOSTS:
        raise ProviderError("Unsupported HiAnime server host")
    parsed = urlsplit(valid_url)
    if parsed.port not in (None, 80, 443):
        raise ProviderError("Unsupported HiAnime server port")
    request_headers = valid_headers({"Referer": referer, "User-Agent": user_agent})
    request_headers["Accept"] = "text/html,application/json"
    response = await fetch_page(client, valid_url, request_headers)
    text = response.text
    if response.headers.get("cf-mitigated", "").lower() == "challenge" or CHALLENGE.search(text):
        raise ProviderError("Server requires a browser challenge; no bypass attempted")
    if re.search(r"Error\s+Code\s*:\s*(?:<[^>]*>\s*)*410\b", text, re.IGNORECASE):
        raise ProviderError("Server content was removed (Error Code 410)")
    response_url = str(response.url)
    media_headers = {"Referer": response_url, "User-Agent": user_agent}
    streams: list[Stream] = []
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type == "application/json" or text.lstrip().startswith(("{", "[")):
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("Server returned invalid JSON") from exc
        streams = streams_from_payload(payload, response_url, media_headers, referrer_policy=True)
    else:
        parser = MediaHTML()
        parser.feed(text)
        if parsed.hostname == "zokoanime.video":
            payload = _zoko_payload(parser.scripts)
            if payload is not None:
                streams = streams_from_payload(payload, response_url, media_headers, referrer_policy=True)
        if not streams:
            streams = streams_from_payload(parser.rows, response_url, media_headers, referrer_policy=True)
            for payload in json_scripts(parser.scripts):
                streams.extend(streams_from_payload(payload, response_url, media_headers, referrer_policy=True))
    if not streams:
        raise ProviderError("Server has no supported explicit media source; its player format may have changed")
    return streams
