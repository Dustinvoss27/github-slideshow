"""Shared helpers: paths, config/state IO, ffmpeg helpers, fonts."""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
OUT = ROOT / "out"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

FONT_CANDIDATES = [
    # Bundled fonts take priority: drop any bold .ttf/.otf into assets/fonts/.
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def load_config() -> dict:
    with open(ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def load_state() -> dict:
    state = load_json(DATA / "state.json", {})
    state.setdefault("used_words", [])
    state.setdefault("processed_vods", [])
    state.setdefault("uploads", [])
    return state


def save_state(state: dict) -> None:
    save_json(DATA / "state.json", state)


def find_font() -> str:
    env = os.environ.get("SHORTS_FONT")
    if env and Path(env).exists():
        return env
    bundled = sorted(p for p in (ASSETS / "fonts").glob("*") if p.suffix.lower() in {".ttf", ".otf"})
    if bundled:
        return str(bundled[0])
    for c in FONT_CANDIDATES:
        if Path(c).exists():
            return c
    raise FileNotFoundError("No bold font found. Put a .ttf in shorts/assets/fonts/ or set SHORTS_FONT.")


def list_files(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in exts and p.is_file())


def pick_random(folder: Path, exts: set[str], rng: random.Random) -> Path | None:
    files = list_files(folder, exts)
    return rng.choice(files) if files else None


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RuntimeError(f"{tool} is not installed or not on PATH")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n{proc.stderr[-4000:]}")


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
