from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from rich.table import Table

from common import CACHE_DIR, PROMPTS_DIR, console, home_dir, read_json, require_dir, write_json
from schemas import BatchDetectionResponse, DetectionsFile, FrameDetection

app = typer.Typer(add_completion=False)

# $ per 1M tokens. Output includes thinking tokens for reasoning models — verify against
# https://ai.google.dev/gemini-api/docs/pricing before trusting cost estimates long-term.
GEMINI_PRICING = {
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

MAX_ATTEMPTS = 2
MAX_TRANSPORT_RETRIES = 6


@dataclass
class BatchUsage:
    input_tokens: int
    output_tokens: int  # candidates + thinking tokens, i.e. what's actually billed as output


@dataclass
class BatchResult:
    batch_index: int
    frame_indices: list[int]
    frames: list[FrameDetection]
    cached: bool
    usage: Optional[BatchUsage]


def load_prompt() -> tuple[str, str]:
    prompt_path = PROMPTS_DIR / "detect.md"
    if not prompt_path.is_file():
        console.print(f"[red]Missing prompt file: {prompt_path}[/red]")
        raise SystemExit(1)
    text = prompt_path.read_text()
    version = f"detect-v1-{hashlib.sha256(text.encode()).hexdigest()[:10]}"
    return text, version


def cache_key(prompt_version: str, frame_paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    hasher.update(prompt_version.encode())
    for path in frame_paths:
        hasher.update(b"|")
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def build_contents(prompt_text: str, frame_paths: list[Path], frame_indices: list[int]) -> list:
    contents: list = [
        prompt_text,
        f"This batch contains {len(frame_paths)} frames, in chronological order, "
        f"with these frame indices: {', '.join(str(i) for i in frame_indices)}.",
    ]
    for path in frame_paths:
        contents.append(types.Part.from_bytes(data=path.read_bytes(), mime_type="image/jpeg"))
    return contents


def save_failure(batch_index: int, attempt: int, raw_text: str) -> Path:
    failures_dir = CACHE_DIR / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)
    path = failures_dir / f"batch_{batch_index:03d}_attempt{attempt}.txt"
    path.write_text(raw_text)
    return path


def retry_delay_seconds(error: genai_errors.APIError) -> Optional[float]:
    details = error.details if isinstance(error.details, dict) else {}
    for entry in details.get("error", {}).get("details", []):
        raw = entry.get("retryDelay")
        if raw and raw.endswith("s"):
            try:
                return float(raw[:-1])
            except ValueError:
                continue
    return None


def call_with_backoff(client: genai.Client, model: str, contents: list, config) -> types.GenerateContentResponse:
    """Retries on rate limits (429) and transient server errors (5xx), honoring the API's
    suggested retryDelay when it provides one. Not for invalid/malformed JSON — that's
    handled by the caller's own retry loop."""
    backoff = 5.0
    for attempt in range(1, MAX_TRANSPORT_RETRIES + 1):
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except (genai_errors.ClientError, genai_errors.ServerError) as e:
            is_rate_limited = isinstance(e, genai_errors.ClientError) and e.code == 429
            if not is_rate_limited and not isinstance(e, genai_errors.ServerError):
                raise
            if attempt == MAX_TRANSPORT_RETRIES:
                raise
            delay = retry_delay_seconds(e) or backoff
            console.print(f"[dim]{e.status or e.code}, retrying in {delay:.0f}s (attempt {attempt})...[/dim]")
            time.sleep(delay)
            backoff = min(backoff * 2, 60.0)
    raise RuntimeError("unreachable")


def process_batch(
    client: genai.Client,
    model: str,
    prompt_text: str,
    prompt_version: str,
    batch_index: int,
    frame_paths: list[Path],
    frame_indices: list[int],
) -> BatchResult:
    key = cache_key(prompt_version, frame_paths)
    cache_path = CACHE_DIR / f"{key}.json"

    if cache_path.is_file():
        payload = read_json(cache_path)
        frames = [FrameDetection.model_validate(f) for f in payload["frames"]]
        console.print(f"[dim][cache] batch {batch_index} (frames {frame_indices[0]}-{frame_indices[-1]})[/dim]")
        return BatchResult(batch_index, frame_indices, frames, cached=True, usage=None)

    contents = build_contents(prompt_text, frame_paths, frame_indices)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=BatchDetectionResponse)

    last_raw = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = call_with_backoff(client, model, contents, config)
        parsed = response.parsed
        if parsed is not None and [f.frame_index for f in parsed.frames] == frame_indices:
            usage_meta = response.usage_metadata
            output_tokens = (usage_meta.candidates_token_count or 0) + (usage_meta.thoughts_token_count or 0)
            usage = BatchUsage(input_tokens=usage_meta.prompt_token_count or 0, output_tokens=output_tokens)
            write_json(cache_path, {"frame_indices": frame_indices, "frames": [f.model_dump(mode="json") for f in parsed.frames]})
            console.print(f"[green][api] batch {batch_index} (frames {frame_indices[0]}-{frame_indices[-1]})[/green]")
            return BatchResult(batch_index, frame_indices, parsed.frames, cached=False, usage=usage)

        try:
            last_raw = response.text
        except Exception:
            last_raw = repr(response)
        saved_path = save_failure(batch_index, attempt, last_raw)
        console.print(
            f"[yellow]batch {batch_index} attempt {attempt} produced an invalid/mismatched response "
            f"(saved to {saved_path})[/yellow]"
        )

    console.print(f"[red]batch {batch_index} (frames {frame_indices}) failed after {MAX_ATTEMPTS} attempts.[/red]")
    raise SystemExit(1)


@app.command()
def main(
    home: str = typer.Option(..., help="Home id, e.g. home-01"),
    batch_size: int = typer.Option(8, help="Keyframes per Gemini call"),
    max_workers: int = typer.Option(3, help="Concurrent batches in flight"),
    model: str = typer.Option("gemini-3.6-flash", help="Gemini model id"),
) -> None:
    home_path = home_dir(home)
    keyframes_dir = require_dir(home_path / "keyframes")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        console.print("[red]GEMINI_API_KEY is not set (check .env)[/red]")
        raise SystemExit(1)

    prompt_text, prompt_version = load_prompt()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    keyframe_paths = sorted(keyframes_dir.glob("*.jpg"))
    if not keyframe_paths:
        console.print(f"[red]No keyframes found in {keyframes_dir}[/red]")
        raise SystemExit(1)

    batches: list[tuple[int, list[Path], list[int]]] = []
    for batch_index, start in enumerate(range(0, len(keyframe_paths), batch_size), start=1):
        chunk = keyframe_paths[start : start + batch_size]
        indices = [int(p.stem) for p in chunk]
        batches.append((batch_index, chunk, indices))

    console.print(
        f"[bold]Detecting[/bold] {len(keyframe_paths)} keyframes in {len(batches)} batches "
        f"of up to {batch_size}, model={model}, prompt_version={prompt_version}"
    )

    client = genai.Client(api_key=api_key)
    results: list[BatchResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(process_batch, client, model, prompt_text, prompt_version, idx, paths, indices): idx
            for idx, paths, indices in batches
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda r: r.batch_index)

    all_frames: list[FrameDetection] = []
    for r in results:
        all_frames.extend(r.frames)
    all_frames.sort(key=lambda f: f.frame_index)

    detections = DetectionsFile(prompt_version=prompt_version, frames=all_frames)
    write_json(home_path / "detections.json", detections.model_dump(mode="json"))

    cache_hits = sum(1 for r in results if r.cached)
    api_calls = len(results) - cache_hits
    total_input = sum(r.usage.input_tokens for r in results if r.usage)
    total_output = sum(r.usage.output_tokens for r in results if r.usage)
    prices = GEMINI_PRICING.get(model)
    if prices:
        cost = (total_input / 1_000_000) * prices["input"] + (total_output / 1_000_000) * prices["output"]
        cost_str = f"${cost:.4f}"
    else:
        cost_str = "unknown (model not in GEMINI_PRICING table)"

    table = Table(title="Stage 03 detect summary")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("keyframes", str(len(keyframe_paths)))
    table.add_row("batches", str(len(batches)))
    table.add_row("cache hits", str(cache_hits))
    table.add_row("api calls", str(api_calls))
    table.add_row("billed input tokens", str(total_input))
    table.add_row("billed output tokens (incl. thinking)", str(total_output))
    table.add_row("estimated cost (this run)", cost_str)
    console.print(table)
    console.print(f"[green]Wrote {home_path / 'detections.json'}[/green]")


if __name__ == "__main__":
    app()
