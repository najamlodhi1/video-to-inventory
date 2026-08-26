from __future__ import annotations

import typer

from common import console

app = typer.Typer(add_completion=False)


@app.command()
def main(home: str = typer.Option(..., help="Home id, e.g. home-01")) -> None:
    console.print("[yellow]Stage 04 (reconcile) not implemented yet — pending schemas.md and prompts/reconcile.md.[/yellow]")
    raise SystemExit(1)


if __name__ == "__main__":
    app()
