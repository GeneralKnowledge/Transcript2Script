"""Extract a YouTube video ID from common URL formats."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(url_or_id: str) -> str:
    """Return an 11-character YouTube video ID from a URL or raw ID."""
    value = url_or_id.strip()
    if _ID_RE.match(value):
        return value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
        if _ID_RE.match(candidate):
            return candidate

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            ids = parse_qs(parsed.query).get("v", [])
            if ids and _ID_RE.match(ids[0]):
                return ids[0]
        for prefix in ("/embed/", "/shorts/", "/live/", "/v/"):
            if parsed.path.startswith(prefix):
                candidate = parsed.path[len(prefix) :].split("/")[0]
                if _ID_RE.match(candidate):
                    return candidate

    raise ValueError(
        f"Could not parse a YouTube video ID from: {url_or_id!r}"
    )
