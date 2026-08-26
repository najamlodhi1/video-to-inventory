from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import cv2
import imagehash
import typer
from PIL import Image

from common import console, home_dir, read_json, require_dir, write_json

app = typer.Typer(add_completion=False)


def sharpness(path: Path) -> float:
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


@dataclass
class FrameRecord:
    frame: str
    window: int
    sharpness: float
    kept: bool
    reason: str
    phash_distance: Optional[int] = None


@app.command()
def main(
    home: str = typer.Option(..., help="Home id, e.g. home-01"),
    blur_threshold: float = typer.Option(40.0, help="Min Laplacian variance to keep a frame"),
    phash_distance: int = typer.Option(5, help="Min Hamming distance from the last kept frame"),
    resize_longest_edge: int = typer.Option(768, help="Resize survivors so the longest edge is this many px"),
    extract_fps: Optional[int] = typer.Option(
        None, help="Frames per 1s window; defaults to extract_meta.json's fps"
    ),
) -> None:
    home_path = home_dir(home)
    frames_dir = require_dir(home_path / "frames")
    keyframes_dir = home_path / "keyframes"
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    for stale in keyframes_dir.glob("*.jpg"):
        stale.unlink()

    window_size = extract_fps
    meta_path = home_path / "extract_meta.json"
    if window_size is None:
        if meta_path.is_file():
            window_size = read_json(meta_path)["fps"]
        else:
            window_size = 6
            console.print("[yellow]No extract_meta.json found, assuming 6 fps windows[/yellow]")

    frame_files = sorted(frames_dir.glob("*.jpg"))
    total_frames = len(frame_files)
    if total_frames == 0:
        console.print(f"[red]No frames found in {frames_dir}[/red]")
        raise SystemExit(1)

    records: list[FrameRecord] = []

    # Pass 1: best-of-N per 1-second window (sharpest frame wins)
    window_winners: list[tuple[Path, float, int]] = []
    for start in range(0, total_frames, window_size):
        window = frame_files[start : start + window_size]
        window_idx = start // window_size
        scored = [(f, sharpness(f)) for f in window]
        best_frame, best_score = max(scored, key=lambda x: x[1])
        for f, score in scored:
            if f != best_frame:
                records.append(FrameRecord(f.name, window_idx, score, False, "not_sharpest_in_window"))
        window_winners.append((best_frame, best_score, window_idx))

    console.print(
        f"Pass 1 (best-of-{window_size} per window): {total_frames} frames -> {len(window_winners)} window winners"
    )

    # Pass 2: blur threshold
    sharp_survivors: list[tuple[Path, float, int]] = []
    for frame, score, window_idx in window_winners:
        if score < blur_threshold:
            records.append(FrameRecord(frame.name, window_idx, score, False, "blur_below_threshold"))
        else:
            sharp_survivors.append((frame, score, window_idx))

    console.print(f"Pass 2 (blur >= {blur_threshold}): {len(window_winners)} -> {len(sharp_survivors)}")

    # Pass 3: perceptual-hash de-dup against the last *kept* frame
    kept: list[tuple[Path, float, int]] = []
    last_hash = None
    for frame, score, window_idx in sharp_survivors:
        with Image.open(frame) as img:
            phash = imagehash.phash(img)
        distance = None
        if last_hash is not None:
            distance = phash - last_hash
            if distance < phash_distance:
                records.append(
                    FrameRecord(frame.name, window_idx, score, False, "duplicate_phash", phash_distance=distance)
                )
                continue
        kept.append((frame, score, window_idx))
        last_hash = phash
        records.append(FrameRecord(frame.name, window_idx, score, True, "kept", phash_distance=distance))

    console.print(f"Pass 3 (phash distance >= {phash_distance}): {len(sharp_survivors)} -> {len(kept)}")

    # Resize survivors and write to keyframes/
    for frame, _, _ in kept:
        with Image.open(frame) as img:
            img = img.convert("RGB")
            w, h = img.size
            longest = max(w, h)
            if longest > resize_longest_edge:
                scale = resize_longest_edge / longest
                img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
            img.save(keyframes_dir / frame.name, "JPEG", quality=90)

    write_json(home_path / "filter_log.json", [asdict(r) for r in records])

    reduction_pct = 100 * (1 - len(kept) / total_frames)
    console.print(f"[green]{total_frames} → {len(kept)} keyframes[/green] (reduction {reduction_pct:.1f}%)")


if __name__ == "__main__":
    app()
