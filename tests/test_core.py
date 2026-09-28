"""Tests for video ID parsing and fact extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from transcript2script.facts import extract_facts_heuristic
from transcript2script.transcript import load_transcript_file
from transcript2script.video_id import extract_video_id

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "black_dahlia_sample.json"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Ti2rs5vvz3Q", "Ti2rs5vvz3Q"),
        ("https://youtu.be/Ti2rs5vvz3Q", "Ti2rs5vvz3Q"),
        ("https://youtu.be/Ti2rs5vvz3Q?si=l8DscE3Y9AFFCSeJ", "Ti2rs5vvz3Q"),
        ("https://www.youtube.com/watch?v=Ti2rs5vvz3Q", "Ti2rs5vvz3Q"),
        ("https://www.youtube.com/embed/Ti2rs5vvz3Q", "Ti2rs5vvz3Q"),
        ("https://www.youtube.com/shorts/Ti2rs5vvz3Q", "Ti2rs5vvz3Q"),
    ],
)
def test_extract_video_id(value: str, expected: str) -> None:
    assert extract_video_id(value) == expected


def test_extract_video_id_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        extract_video_id("https://example.com/not-youtube")


def test_load_sample_and_extract_facts() -> None:
    transcript = load_transcript_file(SAMPLE)
    assert transcript.video_id == "Ti2rs5vvz3Q"
    assert len(transcript.segments) >= 5

    report = extract_facts_heuristic(transcript)
    assert report.fact_count >= 3
    joined = " ".join(fact.claim.lower() for fact in report.facts)
    assert "elizabeth short" in joined or "1947" in joined
    # Promo line should be filtered out.
    assert "subscribe" not in joined
