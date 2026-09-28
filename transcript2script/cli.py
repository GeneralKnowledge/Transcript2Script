"""Command-line interface for Transcript2Script."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import __version__
from .facts import extract_facts
from .transcript import fetch_transcript, load_transcript_file

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Fetch a YouTube transcript and compile facts from it.",
)
console = Console()


@app.callback()
def _load_env() -> None:
    load_dotenv()


def _resolve_transcript(
    url: Optional[str],
    *,
    from_file: Optional[Path],
    languages: Optional[str],
    cookies: Optional[Path],
    backend: str,
):
    if from_file is not None:
        video_id = "local"
        if url:
            try:
                from .video_id import extract_video_id

                video_id = extract_video_id(url)
            except ValueError:
                video_id = url
        try:
            return load_transcript_file(from_file, video_id=video_id)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Failed to load transcript file:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if not url:
        raise typer.BadParameter("Provide a YouTube URL/ID, or --from-file.")

    langs = [part.strip() for part in languages.split(",")] if languages else None
    try:
        return fetch_transcript(
            url,
            languages=langs,
            cookies=str(cookies) if cookies else None,
            backend=backend,
        )
    except RuntimeError as exc:
        console.print(f"[red]Could not fetch transcript[/red]\n{exc}")
        raise typer.Exit(code=1) from exc


@app.command("transcript")
def transcript_cmd(
    url: Optional[str] = typer.Argument(
        None, help="YouTube URL or video ID"
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="Load transcript from .txt/.vtt/.srt/.json instead of YouTube",
    ),
    languages: Optional[str] = typer.Option(
        None,
        "--languages",
        "-l",
        help="Comma-separated language codes, e.g. en,en-US",
    ),
    cookies: Optional[Path] = typer.Option(
        None,
        "--cookies",
        help="Netscape-format cookies.txt for YouTube (helps when IP is blocked)",
    ),
    backend: str = typer.Option(
        "auto",
        "--backend",
        help="Transcript backend: auto | youtube_transcript_api | ytdlp",
    ),
    timed: bool = typer.Option(
        False,
        "--timed",
        help="Include timestamps in the printed transcript",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write transcript text to this file",
    ),
) -> None:
    """Download and print the transcript for a YouTube video."""
    with console.status("Loading transcript..."):
        result = _resolve_transcript(
            url,
            from_file=from_file,
            languages=languages,
            cookies=cookies,
            backend=backend,
        )

    text = result.timed_text() if timed else result.text
    title = result.title or result.video_id
    console.print(
        Panel.fit(
            f"[bold]{title}[/bold]\n"
            f"{result.video_id} · {result.language} "
            f"({'auto-generated' if result.is_generated else 'manual'}) · "
            f"{len(result.segments)} segments",
            title="Transcript",
        )
    )
    console.print(text)

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        console.print(f"\n[green]Wrote[/green] {output}")


@app.command("facts")
def facts_cmd(
    url: Optional[str] = typer.Argument(
        None, help="YouTube URL or video ID"
    ),
    from_file: Optional[Path] = typer.Option(
        None,
        "--from-file",
        help="Load transcript from .txt/.vtt/.srt/.json instead of YouTube",
    ),
    method: str = typer.Option(
        "auto",
        "--method",
        "-m",
        help="Fact extraction method: auto | llm | heuristic",
    ),
    languages: Optional[str] = typer.Option(
        None,
        "--languages",
        "-l",
        help="Comma-separated language codes, e.g. en,en-US",
    ),
    cookies: Optional[Path] = typer.Option(
        None,
        "--cookies",
        help="Netscape-format cookies.txt for YouTube (helps when IP is blocked)",
    ),
    backend: str = typer.Option(
        "auto",
        "--backend",
        help="Transcript backend: auto | youtube_transcript_api | ytdlp",
    ),
    limit: int = typer.Option(40, "--limit", help="Maximum number of facts"),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="OpenAI model override when using LLM extraction",
    ),
    format: str = typer.Option(
        "markdown",
        "--format",
        "-f",
        help="Output format: markdown | json",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Write facts to this file",
    ),
) -> None:
    """Fetch a transcript and compile a list of facts from the video."""
    if method not in {"auto", "llm", "heuristic"}:
        raise typer.BadParameter("method must be one of: auto, llm, heuristic")
    if format not in {"markdown", "json"}:
        raise typer.BadParameter("format must be one of: markdown, json")

    with console.status("Loading transcript..."):
        transcript = _resolve_transcript(
            url,
            from_file=from_file,
            languages=languages,
            cookies=cookies,
            backend=backend,
        )

    try:
        with console.status(f"Extracting facts ({method})..."):
            report = extract_facts(
                transcript,
                method=method,
                model=model,
                limit=limit,
            )
    except RuntimeError as exc:
        console.print(f"[red]Fact extraction failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if format == "json":
        rendered = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        console.print_json(rendered)
    else:
        rendered = report.to_markdown()
        console.print(Markdown(rendered))

    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.suffix.lower() == ".json" or format == "json":
            output.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        else:
            output.write_text(
                rendered if format == "markdown" else report.to_markdown(),
                encoding="utf-8",
            )
        console.print(f"\n[green]Wrote[/green] {output}")


@app.command("version")
def version_cmd() -> None:
    """Print the package version."""
    console.print(__version__)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
