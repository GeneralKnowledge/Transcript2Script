"""Compile factual claims from a transcript."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass

from .transcript import Transcript


@dataclass(frozen=True)
class Fact:
    claim: str
    timestamp: str | None = None
    confidence: str = "medium"
    category: str | None = None


@dataclass(frozen=True)
class FactReport:
    video_id: str
    video_url: str
    source: str
    language: str
    fact_count: int
    facts: list[Fact]
    summary: str | None = None

    def to_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "video_url": self.video_url,
            "source": self.source,
            "language": self.language,
            "fact_count": self.fact_count,
            "summary": self.summary,
            "facts": [asdict(fact) for fact in self.facts],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Facts from YouTube video `{self.video_id}`",
            "",
            f"- URL: {self.video_url}",
            f"- Transcript language: {self.language}",
            f"- Extraction method: {self.source}",
            f"- Facts found: {self.fact_count}",
            "",
        ]
        if self.summary:
            lines.extend(["## Summary", "", self.summary, ""])
        lines.append("## Facts")
        lines.append("")
        for i, fact in enumerate(self.facts, start=1):
            meta: list[str] = []
            if fact.timestamp:
                meta.append(fact.timestamp)
            if fact.category:
                meta.append(fact.category)
            if fact.confidence:
                meta.append(f"confidence: {fact.confidence}")
            suffix = f" ({', '.join(meta)})" if meta else ""
            lines.append(f"{i}. {fact.claim}{suffix}")
        lines.append("")
        return "\n".join(lines)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_FACTISH = re.compile(
    r"\b("
    r"\d[\d,]*(?:\.\d+)?%?"
    r"|million|billion|trillion|thousand"
    r"|according to|research|study|found|shows|reveals"
    r"|is the|was the|are the|were the"
    r"|invented|discovered|founded|created|built"
    r"|born|died|first|largest|smallest|oldest|newest"
    r"|because|therefore|in fact|notably"
    r")\b",
    re.IGNORECASE,
)
_NOISE = re.compile(
    r"\b(subscribe|like and subscribe|comment below|smash that|thanks for watching|"
    r"follow me|patreon|sponsor|click the bell|don'?t forget to)\b",
    re.IGNORECASE,
)


def _nearest_timestamp(transcript: Transcript, claim: str) -> str | None:
    claim_l = claim.lower()
    best = None
    best_score = 0
    claim_words = {w for w in re.findall(r"[a-z0-9']+", claim_l) if len(w) > 3}
    if not claim_words:
        return None
    for segment in transcript.segments:
        words = {w for w in re.findall(r"[a-z0-9']+", segment.text.lower()) if len(w) > 3}
        score = len(claim_words & words)
        if score > best_score:
            best_score = score
            best = segment.timestamp()
    if best_score >= 2:
        return best
    return None


def extract_facts_heuristic(transcript: Transcript, *, limit: int = 40) -> FactReport:
    """Extract likely factual sentences without calling an external LLM."""
    text = transcript.text
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    facts: list[Fact] = []
    seen: set[str] = set()

    for sentence in sentences:
        cleaned = " ".join(sentence.split())
        if len(cleaned) < 40 or len(cleaned) > 320:
            continue
        if _NOISE.search(cleaned):
            continue
        if not _FACTISH.search(cleaned):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            Fact(
                claim=cleaned if cleaned.endswith((".", "!", "?")) else cleaned + ".",
                timestamp=_nearest_timestamp(transcript, cleaned),
                confidence="low",
                category="heuristic",
            )
        )
        if len(facts) >= limit:
            break

    return FactReport(
        video_id=transcript.video_id,
        video_url=f"https://youtu.be/{transcript.video_id}",
        source="heuristic",
        language=transcript.language,
        fact_count=len(facts),
        facts=facts,
        summary=(
            f"Heuristic extraction found {len(facts)} candidate factual statements "
            f"from the transcript. For higher-quality results, set OPENAI_API_KEY."
        ),
    )


def extract_facts_llm(
    transcript: Transcript,
    *,
    model: str | None = None,
    limit: int = 40,
) -> FactReport:
    """Use OpenAI to compile a structured fact list from the transcript."""
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    client = OpenAI(api_key=api_key)
    chosen_model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Cap prompt size while keeping timestamps for grounding.
    timed = transcript.timed_text()
    if len(timed) > 60_000:
        timed = timed[:60_000] + "\n...[transcript truncated]..."

    system = (
        "You extract clear, verifiable-sounding facts from video transcripts. "
        "Prefer concrete claims (names, dates, numbers, causal statements, definitions). "
        "Ignore ads, sponsorships, greetings, and calls to action. "
        "Do not invent facts that are not supported by the transcript. "
        "Return strict JSON only."
    )
    user = f"""Extract up to {limit} distinct facts from this YouTube transcript.

Return JSON with this shape:
{{
  "summary": "2-4 sentence overview of what the video is about",
  "facts": [
    {{
      "claim": "one clear factual statement",
      "timestamp": "MM:SS or HH:MM:SS if identifiable, else null",
      "confidence": "high|medium|low",
      "category": "short category label"
    }}
  ]
}}

Transcript with timestamps:
{timed}
"""

    response = client.chat.completions.create(
        model=chosen_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = response.choices[0].message.content or "{}"
    payload = json.loads(content)
    raw_facts = payload.get("facts") or []
    facts: list[Fact] = []
    for item in raw_facts[:limit]:
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        facts.append(
            Fact(
                claim=claim,
                timestamp=item.get("timestamp"),
                confidence=str(item.get("confidence") or "medium"),
                category=item.get("category"),
            )
        )

    return FactReport(
        video_id=transcript.video_id,
        video_url=f"https://youtu.be/{transcript.video_id}",
        source=f"openai:{chosen_model}",
        language=transcript.language,
        fact_count=len(facts),
        facts=facts,
        summary=(payload.get("summary") or None),
    )


def extract_facts(
    transcript: Transcript,
    *,
    method: str = "auto",
    model: str | None = None,
    limit: int = 40,
) -> FactReport:
    """Extract facts using LLM when available, otherwise heuristics."""
    if method == "heuristic":
        return extract_facts_heuristic(transcript, limit=limit)
    if method == "llm":
        return extract_facts_llm(transcript, model=model, limit=limit)
    if method == "auto":
        if os.getenv("OPENAI_API_KEY"):
            return extract_facts_llm(transcript, model=model, limit=limit)
        return extract_facts_heuristic(transcript, limit=limit)
    raise ValueError(f"Unknown method: {method!r}. Use auto, llm, or heuristic.")
