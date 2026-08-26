from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer

from common import console

app = typer.Typer(add_completion=False)

STAGES = {
    1: "01_extract.py",
    2: "02_filter.py",
    3: "03_detect.py",
    4: "04_reconcile.py",
    5: "05_price.py",
}

PIPELINE_DIR = Path(__file__).resolve().parent


@app.command()
def main(
    home: str = typer.Option(..., help="Home id, e.g. home-01"),
    from_: int = typer.Option(1, "--from", min=1, max=5, help="First stage to run"),
    to: int = typer.Option(5, "--to", min=1, max=5, help="Last stage to run"),
) -> None:
    if from_ > to:
        console.print("[red]--from must be <= --to[/red]")
        raise SystemExit(1)

    for stage_num in range(from_, to + 1):
        script = PIPELINE_DIR / STAGES[stage_num]
        console.print(f"[bold cyan]== Stage {stage_num}: {script.name} ==[/bold cyan]")
        result = subprocess.run([sys.executable, str(script), "--home", home])
        if result.returncode != 0:
            console.print(f"[red]Stage {stage_num} ({script.name}) failed, stopping.[/red]")
            raise SystemExit(result.returncode)

    console.print("[green]Pipeline complete.[/green]")


if __name__ == "__main__":
    app()
