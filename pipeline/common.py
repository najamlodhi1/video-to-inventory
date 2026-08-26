from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

console = Console()

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = REPO_ROOT / ".cache"
PROMPTS_DIR = REPO_ROOT / "prompts"
CATALOGUE_PATH = REPO_ROOT / "catalogue" / "items.json"


def home_dir(home: str) -> Path:
    return DATA_DIR / home


def require_dir(path: Path) -> Path:
    if not path.is_dir():
        console.print(f"[red]Missing required directory: {path}[/red]")
        raise SystemExit(1)
    return path


def require_file(path: Path) -> Path:
    if not path.is_file():
        console.print(f"[red]Missing required file: {path}[/red]")
        raise SystemExit(1)
    return path


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())
