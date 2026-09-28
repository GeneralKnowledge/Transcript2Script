# Transcript2Script

Fetch a YouTube video's transcript, then compile a clean list of facts from it.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### Fetch a transcript

```bash
python -m transcript2script transcript "https://youtu.be/Ti2rs5vvz3Q"
```

### Compile facts

```bash
# Heuristic extraction (no API key needed)
python -m transcript2script facts "https://youtu.be/Ti2rs5vvz3Q" \
  --method heuristic \
  --output output/facts.md

# Higher-quality LLM extraction (requires OPENAI_API_KEY)
cp .env.example .env   # then add your key
python -m transcript2script facts "https://youtu.be/Ti2rs5vvz3Q" \
  --method llm \
  --format json \
  --output output/facts.json
```

## How it works

1. **Transcript fetch** — tries `youtube-transcript-api`, then falls back to `yt-dlp` subtitles.
2. **Fact extraction**
   - `heuristic`: picks sentence-like claims with dates, numbers, causal language, etc.
   - `llm`: asks OpenAI to return structured facts + a short summary (JSON).
   - `auto`: uses LLM when `OPENAI_API_KEY` is set, otherwise heuristic.

## When YouTube blocks cloud IPs

YouTube often refuses transcript requests from datacenter IPs. Options:

| Option | How |
| --- | --- |
| Run locally | Best default on a home/residential network |
| Cookies | Export a Netscape `cookies.txt` and pass `--cookies cookies.txt` (or set `YOUTUBE_COOKIES`) |
| HTTP proxy | Set `HTTP_PROXY` / `HTTPS_PROXY` |
| Webshare | Set `WEBSHARE_PROXY_USERNAME` and `WEBSHARE_PROXY_PASSWORD` |
| Local file | Save captions somehow, then use `--from-file` |

### Demo without live YouTube access

A sample transcript for the Black Dahlia video topic is included:

```bash
python -m transcript2script facts \
  --from-file samples/black_dahlia_sample.json \
  "https://youtu.be/Ti2rs5vvz3Q" \
  --method heuristic \
  --output output/sample-facts.md
```

> The sample file is a stand-in for offline demos. Replace it with a real caption export for production use.

## CLI reference

```text
python -m transcript2script transcript URL [options]
python -m transcript2script facts URL [options]
```

Useful flags:

- `--from-file PATH` — load `.txt` / `.vtt` / `.srt` / `.json` instead of hitting YouTube
- `--cookies PATH` — Netscape cookie jar for yt-dlp / authenticated fetches
- `--backend auto|youtube_transcript_api|ytdlp`
- `--method auto|llm|heuristic`
- `--format markdown|json`
- `--output PATH`
- `--limit N`
- `--timed` (transcript command)

## Project layout

```text
transcript2script/
  video_id.py      # URL → video ID
  transcript.py    # fetch / parse transcripts
  facts.py         # heuristic + LLM fact compilers
  cli.py           # Typer CLI
samples/           # offline demo transcript
tests/             # unit tests
```

## Tests

```bash
pytest
```
