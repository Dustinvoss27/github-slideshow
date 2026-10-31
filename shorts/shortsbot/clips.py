"""Gameplay clipping: find the loudest/most hype moments in a long recording and cut vertical Shorts.

Only use footage you recorded yourself or have explicit permission to clip
(e.g. a streamer's official clipping program). Re-uploading other people's
gameplay/streams gets channels copyright-striked and demonetized.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .common import hex_to_rgb, probe_duration, run_ffmpeg
from .render import Fonts, _fit

SR = 8000


def loudness_curve(vod: Path) -> np.ndarray:
    """Per-second RMS loudness of the audio track (mono, 8 kHz)."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(vod), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
        capture_output=True, check=True,
    )
    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    secs = len(pcm) // SR
    if secs == 0:
        return np.zeros(0)
    frames = pcm[: secs * SR].reshape(secs, SR)
    return np.sqrt((frames ** 2).mean(axis=1) + 1e-9)


def find_highlights(curve: np.ndarray, clip_len: int, count: int, peak_pos: float, min_gap: int,
                    min_jump: float = 1.3) -> list[int]:
    """Return start seconds of the top `count` moments, with the peak `peak_pos` of the way in.

    Scores each second by loudness relative to the surrounding minute, so a sudden scream/explosion
    beats a constantly loud section.
    """
    n = len(curve)
    if n < clip_len + 2:
        return [0] if n else []  # short recording: use all of it
    def smooth(x, k):  # moving average that doesn't sag at the edges
        w = np.ones(k)
        return np.convolve(x, w, mode="same") / np.convolve(np.ones_like(x), w, mode="same")

    short = smooth(curve, 3)
    baseline = smooth(curve, min(61, n if n % 2 else n - 1)) + 1e-6
    # relative jump, weighted by absolute loudness so silent-but-noisy parts don't win
    jump = short / baseline
    score = jump * np.sqrt(short / (curve.max() + 1e-9))
    picks: list[int] = []
    for peak in np.argsort(score)[::-1]:
        if jump[peak] < min_jump:  # nothing louder than its surroundings is left
            break
        start = int(peak - clip_len * peak_pos)
        start = max(0, min(start, n - clip_len))
        if all(abs(start - p) >= min_gap for p in picks):
            picks.append(start)
        if len(picks) >= count:
            break
    return sorted(picks)


def _hook_png(text: str, font_path: str, accent: str, W: int, path: Path) -> None:
    img = Image.new("RGBA", (W, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fonts = Fonts(font_path)
    f, size = _fit(d, text.upper(), fonts, W - 120, 96)
    l, t, r, b = d.textbbox((W // 2, 180), text.upper(), font=f, anchor="mm")
    d.rounded_rectangle([l - 36, t - 28, r + 36, b + 28], radius=30, fill=(*hex_to_rgb(accent), 255))
    d.text((W // 2, 180), text.upper(), font=f, fill=(0, 0, 0, 255), anchor="mm")
    img.save(path)


def cut_vertical(vod: Path, start: float, length: float, hook: str, font_path: str, accent: str,
                 cfg: dict, out: Path, workdir: Path) -> Path:
    v = cfg["video"]
    W, H = v["width"], v["height"]
    hook_png = workdir / f"{out.stem}_hook.png"
    _hook_png(hook, font_path, accent, W, hook_png)
    # 16:9 gameplay centred on a blurred, zoomed copy of itself (standard vertical-clip layout)
    filters = ";".join([
        "[0:v]split[a][b]",
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:2,"
        f"eq=brightness=-0.15[bg]",
        f"[b]scale={W}:-2[fg]",
        "[bg][fg]overlay=0:(H-h)/2[v1]",
        f"[v1][1:v]overlay=0:{int(H * 0.12)}:enable='lt(t,{min(4.0, length):.1f})',"
        f"fps={v['fps']},format=yuv420p[v]",
        "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]",
    ])
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(vod), "-loop", "1", "-i", str(hook_png),
        "-filter_complex", filters, "-map", "[v]", "-map", "[a]", "-t", f"{length:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out),
    ])
    return out


def make_clips(vod: Path, cfg: dict, font_path: str, accent: str, out_dir: Path, workdir: Path,
               rng: random.Random) -> list[dict]:
    c = cfg["clips"]
    duration = probe_duration(vod)
    clip_len = int(min(c["clip_seconds"], max(5, duration)))
    curve = loudness_curve(vod)
    starts = find_highlights(curve, clip_len, c["clips_per_vod"], c["peak_position"], c["min_gap_seconds"],
                             c.get("min_loudness_jump", 1.3))
    results = []
    hooks = rng.sample(c["hook_lines"], k=min(len(starts), len(c["hook_lines"])))
    for i, start in enumerate(starts):
        hook = hooks[i % len(hooks)]
        out = out_dir / f"{vod.stem}_clip{i + 1}.mp4"
        cut_vertical(vod, start, clip_len, hook, font_path, accent, cfg, out, workdir)
        print(f"[clips] {out.name}: {start}s-{start + clip_len}s  hook='{hook}'")
        results.append({"path": out, "start": start, "hook": hook})
    return results
