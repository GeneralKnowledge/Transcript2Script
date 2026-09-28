"""Fetch captions / transcripts for a YouTube video."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
)
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig

from .video_id import extract_video_id


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start: float
    duration: float

    def timestamp(self) -> str:
        total = max(0, int(self.start))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


@dataclass(frozen=True)
class Transcript:
    video_id: str
    language: str
    language_code: str
    is_generated: bool
    segments: list[TranscriptSegment]
    title: str | None = None

    @property
    def text(self) -> str:
        return " ".join(
            segment.text.strip() for segment in self.segments if segment.text.strip()
        )

    def timed_text(self) -> str:
        lines: list[str] = []
        for segment in self.segments:
            cleaned = " ".join(segment.text.split())
            if cleaned:
                lines.append(f"[{segment.timestamp()}] {cleaned}")
        return "\n".join(lines)


def _proxy_config():
    """Build a proxy config from environment variables, if present."""
    webshare_user = os.getenv("WEBSHARE_PROXY_USERNAME")
    webshare_pass = os.getenv("WEBSHARE_PROXY_PASSWORD")
    if webshare_user and webshare_pass:
        return WebshareProxyConfig(
            proxy_username=webshare_user,
            proxy_password=webshare_pass,
        )

    http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
    https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or http_proxy
    if http_proxy or https_proxy:
        return GenericProxyConfig(
            http_url=http_proxy,
            https_url=https_proxy,
        )
    return None


def _fetch_via_youtube_transcript_api(
    video_id: str,
    preferred: list[str],
) -> Transcript:
    api = YouTubeTranscriptApi(proxy_config=_proxy_config())
    transcript_list = api.list(video_id)

    try:
        transcript = transcript_list.find_transcript(preferred)
    except NoTranscriptFound:
        try:
            transcript = transcript_list.find_generated_transcript(preferred)
        except NoTranscriptFound:
            available = list(transcript_list)
            if not available:
                raise RuntimeError(f"No transcripts found for video {video_id}.")
            transcript = available[0]
            if (
                transcript.language_code.split("-")[0] not in {
                    code.split("-")[0] for code in preferred
                }
                and transcript.is_translatable
            ):
                transcript = transcript.translate("en")

    fetched = transcript.fetch()
    segments = [
        TranscriptSegment(
            text=item.text,
            start=float(item.start),
            duration=float(item.duration),
        )
        for item in fetched
    ]
    return Transcript(
        video_id=video_id,
        language=transcript.language,
        language_code=transcript.language_code,
        is_generated=transcript.is_generated,
        segments=segments,
    )


_VTT_TS = re.compile(
    r"(?:(\d{2}):)?(\d{2}):(\d{2})[\.,](\d{3})\s-->\s(?:(\d{2}):)?(\d{2}):(\d{2})[\.,](\d{3})"
)
_SRT_TS = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[\.,](\d{3})\s-->\s(\d{2}):(\d{2}):(\d{2})[\.,](\d{3})"
)


def _hms_to_seconds(
    hours: str | None, minutes: str, seconds: str, millis: str
) -> float:
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(millis) / 1000.0
    )


def _parse_vtt(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        ts_line = next((line for line in lines if "-->" in line), None)
        if not ts_line:
            continue
        match = _VTT_TS.search(ts_line)
        if not match:
            continue
        start = _hms_to_seconds(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _hms_to_seconds(match.group(5), match.group(6), match.group(7), match.group(8))
        text_lines = [line for line in lines if "-->" not in line and not line.isdigit()]
        # Drop WEBVTT header / NOTE cues.
        text_lines = [line for line in text_lines if not line.startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))]
        text = " ".join(text_lines)
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            segments.append(TranscriptSegment(text=text, start=start, duration=max(0.0, end - start)))
    return segments


def _parse_srt(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        ts_idx = 0
        if lines[0].isdigit():
            ts_idx = 1
        if ts_idx >= len(lines):
            continue
        match = _SRT_TS.search(lines[ts_idx])
        if not match:
            continue
        start = _hms_to_seconds(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _hms_to_seconds(match.group(5), match.group(6), match.group(7), match.group(8))
        text = " ".join(lines[ts_idx + 1 :])
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            segments.append(TranscriptSegment(text=text, start=start, duration=max(0.0, end - start)))
    return segments


def _parse_json_transcript(data: dict | list) -> list[TranscriptSegment]:
    if isinstance(data, dict) and "segments" in data:
        items = data["segments"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("JSON transcript must be a list or an object with 'segments'.")

    segments: list[TranscriptSegment] = []
    for item in items:
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = float(item.get("start", item.get("offset", 0)) or 0)
        duration = float(item.get("duration", item.get("dur", 0)) or 0)
        segments.append(TranscriptSegment(text=text, start=start, duration=duration))
    return segments


def load_transcript_file(
    path: str | Path,
    *,
    video_id: str = "local",
    language: str = "unknown",
    language_code: str = "und",
) -> Transcript:
    """Load a transcript from .txt, .vtt, .srt, or .json."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {file_path}")

    content = file_path.read_text(encoding="utf-8")
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        data = json.loads(content)
        segments = _parse_json_transcript(data)
        if isinstance(data, dict):
            video_id = str(data.get("video_id") or video_id)
            language = str(data.get("language") or language)
            language_code = str(data.get("language_code") or language_code)
            title = data.get("title")
        else:
            title = None
    elif suffix == ".vtt":
        segments = _parse_vtt(content)
        title = None
    elif suffix == ".srt":
        segments = _parse_srt(content)
        title = None
    else:
        # Plain text: treat as one block, optionally with [MM:SS] prefixes.
        segments = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            ts_match = re.match(r"^\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.+)$", line)
            if ts_match:
                if ts_match.group(3) is not None:
                    start = (
                        int(ts_match.group(1)) * 3600
                        + int(ts_match.group(2)) * 60
                        + int(ts_match.group(3))
                    )
                    text = ts_match.group(4)
                else:
                    start = int(ts_match.group(1)) * 60 + int(ts_match.group(2))
                    text = ts_match.group(4)
                segments.append(TranscriptSegment(text=text, start=float(start), duration=0.0))
            else:
                segments.append(TranscriptSegment(text=line, start=float(len(segments) * 5), duration=5.0))
        title = None

    if not segments:
        raise ValueError(f"No transcript segments found in {file_path}")

    return Transcript(
        video_id=video_id,
        language=language,
        language_code=language_code,
        is_generated=False,
        segments=segments,
        title=title,
    )


def _fetch_via_ytdlp(
    video_id: str,
    preferred: list[str],
    *,
    cookies: str | None = None,
) -> Transcript:
    """Fallback using yt-dlp subtitle download (supports cookies)."""
    import tempfile
    from pathlib import Path as _Path

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is required for the fallback fetcher. Install with: pip install yt-dlp"
        ) from exc

    cookiefile = cookies or os.getenv("YOUTUBE_COOKIES")
    with tempfile.TemporaryDirectory(prefix="t2s-subs-") as tmp:
        outtmpl = str(_Path(tmp) / "%(id)s.%(ext)s")
        ydl_opts: dict = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": preferred + ["en.*"],
            "subtitlesformat": "vtt",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
        }
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=True,
            )

        title = (info or {}).get("title")
        # Prefer requested languages; otherwise first downloaded VTT.
        candidates = sorted(_Path(tmp).glob(f"{video_id}*.vtt"))
        if not candidates:
            raise RuntimeError(
                f"yt-dlp found no subtitle files for {video_id}."
            )

        chosen = candidates[0]
        for lang in preferred:
            for path in candidates:
                if f".{lang}." in path.name or path.name.endswith(f".{lang}.vtt"):
                    chosen = path
                    break
            else:
                continue
            break

        segments = _parse_vtt(chosen.read_text(encoding="utf-8"))
        lang_code = chosen.name[len(video_id) + 1 : -4]  # strip id. and .vtt
        return Transcript(
            video_id=video_id,
            language=lang_code,
            language_code=lang_code,
            is_generated="auto" in chosen.name or "a." in chosen.name,
            segments=segments,
            title=title,
        )


def fetch_transcript(
    url_or_id: str,
    *,
    languages: list[str] | None = None,
    cookies: str | None = None,
    backend: str = "auto",
) -> Transcript:
    """Download the best available transcript for a YouTube video.

    Backends:
      - youtube_transcript_api (default)
      - ytdlp (useful with --cookies when cloud IPs are blocked)
      - auto: try API first, then yt-dlp
    """
    video_id = extract_video_id(url_or_id)
    preferred = languages or ["en", "en-US", "en-GB"]

    errors: list[str] = []
    backends = (
        ["youtube_transcript_api", "ytdlp"]
        if backend == "auto"
        else [backend]
    )

    for name in backends:
        try:
            if name == "youtube_transcript_api":
                return _fetch_via_youtube_transcript_api(video_id, preferred)
            if name == "ytdlp":
                return _fetch_via_ytdlp(video_id, preferred, cookies=cookies)
            raise ValueError(f"Unknown backend: {name!r}")
        except (RequestBlocked, IpBlocked) as exc:
            errors.append(f"{name}: YouTube blocked this IP ({exc.__class__.__name__})")
        except TranscriptsDisabled:
            errors.append(f"{name}: transcripts disabled for this video")
        except VideoUnavailable:
            errors.append(f"{name}: video unavailable")
        except Exception as exc:  # noqa: BLE001 - collect backend errors for a joint message
            errors.append(f"{name}: {exc}")

    advice = (
        "YouTube often blocks cloud/datacenter IPs. Try one of:\n"
        "  1. Run this locally on a residential network\n"
        "  2. Pass cookies: --cookies /path/to/youtube.cookies.txt\n"
        "  3. Set WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD\n"
        "  4. Set HTTP_PROXY / HTTPS_PROXY\n"
        "  5. Use a saved transcript: --from-file transcript.vtt"
    )
    raise RuntimeError(
        f"Could not fetch transcript for {video_id}.\n"
        + "\n".join(f"- {err}" for err in errors)
        + f"\n\n{advice}"
    )
