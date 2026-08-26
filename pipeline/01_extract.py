from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from PIL import Image

from common import console, home_dir, require_file, write_json

app = typer.Typer(add_completion=False)


def ffprobe_stream_info(video_path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height:stream_tags=rotate:side_data_list",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]ffprobe failed:[/red]\n{e.stderr}")
        raise SystemExit(1)
    return json.loads(result.stdout)


def detect_rotation(probe: dict) -> int:
    stream = probe.get("streams", [{}])[0]
    rotate_tag = stream.get("tags", {}).get("rotate")
    if rotate_tag is not None:
        return int(rotate_tag)
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return abs(int(side_data["rotation"]))
    return 0


@app.command()
def main(
    home: str = typer.Option(..., help="Home id, e.g. home-01"),
    fps: int = typer.Option(6, help="Frames per second to extract"),
    video: str = typer.Option("video.mp4", help="Video filename inside the home dir"),
) -> None:
    home_path = home_dir(home)
    video_path = require_file(home_path / video)
    frames_dir = home_path / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.jpg"):
        stale.unlink()

    probe = ffprobe_stream_info(video_path)
    stream = probe.get("streams", [{}])[0]
    raw_width, raw_height = stream.get("width"), stream.get("height")
    rotation = detect_rotation(probe)

    console.print(f"[bold]Extracting[/bold] {video_path} at {fps} fps -> {frames_dir}")
    console.print(f"ffprobe stream dims: {raw_width}x{raw_height}, rotation metadata: {rotation} deg")

    cmd = ["ffmpeg", "-y", "-i", str(video_path), "-vf", f"fps={fps}", str(frames_dir / "%04d.jpg")]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]ffmpeg failed:[/red]\n{e.stderr}")
        raise SystemExit(1)

    frame_files = sorted(frames_dir.glob("*.jpg"))
    frame_count = len(frame_files)
    if frame_count == 0:
        console.print("[red]No frames extracted — check ffmpeg output/video file.[/red]")
        raise SystemExit(1)

    with Image.open(frame_files[0]) as img:
        actual_width, actual_height = img.size

    if (raw_width, raw_height) != (actual_width, actual_height):
        console.print(
            f"[yellow]Orientation note:[/yellow] ffprobe reported {raw_width}x{raw_height} "
            f"but extracted frames measure {actual_width}x{actual_height} "
            f"(rotation metadata {rotation} deg applied by ffmpeg)."
        )

    write_json(
        home_path / "extract_meta.json",
        {
            "video": video,
            "fps": fps,
            "frame_count": frame_count,
            "raw_stream_width": raw_width,
            "raw_stream_height": raw_height,
            "rotation_degrees": rotation,
            "actual_frame_width": actual_width,
            "actual_frame_height": actual_height,
        },
    )

    console.print(f"[green]Extracted {frame_count} frames[/green] ({actual_width}x{actual_height})")


if __name__ == "__main__":
    app()
