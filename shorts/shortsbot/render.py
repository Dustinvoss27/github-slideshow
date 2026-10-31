"""Compose the vertical video: gameplay/gradient background + word card + karaoke captions."""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import (ASSETS, AUDIO_EXTS, VIDEO_EXTS, hex_to_rgb, pick_random,
                     probe_duration, run_ffmpeg)

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


# ---------------------------------------------------------------- text helpers
class Fonts:
    def __init__(self, path: str):
        self.path = path
        self._cache: dict[int, ImageFont.FreeTypeFont] = {}

    def __call__(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._cache:
            self._cache[size] = ImageFont.truetype(self.path, size)
        return self._cache[size]


def _text_w(draw: ImageDraw.ImageDraw, text: str, font, stroke: int = 0) -> int:
    l, _, r, _ = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return r - l


def _fit(draw, text, fonts: Fonts, max_w: int, start: int, minimum: int = 40, stroke_ratio=0.08):
    size = start
    while size > minimum and _text_w(draw, text, fonts(size), int(size * stroke_ratio)) > max_w:
        size -= 4
    return fonts(size), size


def _wrap(draw, text, font, max_w) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if _text_w(draw, test, font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def chunk_words(words, max_words=3, max_chars=16):
    """Group word timings into short caption chunks (break after punctuation)."""
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[0] for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars or w[0][-1] in ".,!?:;":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- frame drawing
class Painter:
    def __init__(self, W, H, fonts: Fonts, theme: dict, word: dict, day: int, handle: str):
        self.W, self.H, self.fonts, self.word, self.day, self.handle = W, H, fonts, word, day, handle
        self.accent = (*hex_to_rgb(theme["accent"]), 255)
        self.panel = tuple(theme.get("panel", [0, 0, 0, 170]))

    def frame(self, show_card: bool, chunk, active_idx: int | None, path: Path):
        img = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        self._badge(d)
        if show_card:
            self._card(img, d)
        if chunk:
            self._caption(d, chunk, active_idx, y_center=int(self.H * (0.62 if show_card else 0.47)))
        self._handle(d)
        img.save(path, compress_level=1)

    def _badge(self, d):
        f = self.fonts(44)
        label = f"WORD OF THE DAY  #{self.day}"
        w = _text_w(d, label, f)
        x0, y0 = (self.W - w) // 2 - 36, 150
        d.rounded_rectangle([x0, y0, x0 + w + 72, y0 + 84], radius=42, fill=self.accent)
        d.text((self.W // 2, y0 + 42), label, font=f, fill=BLACK, anchor="mm")

    def _card(self, img, d):
        W = self.W
        top, bottom = 290, 860
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rounded_rectangle([60, top, W - 60, bottom], radius=48, fill=self.panel)
        img.alpha_composite(overlay)
        d = ImageDraw.Draw(img)
        word = self.word["word"]
        f, size = _fit(d, word, self.fonts, W - 200, 190)
        d.text((W // 2, top + 190), word, font=f, fill=self.accent, anchor="mm",
               stroke_width=max(4, size // 16), stroke_fill=BLACK)
        d.text((W // 2, top + 335), f"/ {self.word['pronunciation']} /", font=self.fonts(58),
               fill=WHITE, anchor="mm")
        d.text((W // 2, top + 430), self.word["part_of_speech"].lower(), font=self.fonts(48),
               fill=(*self.accent[:3], 230), anchor="mm")
        defn = self.word["definition"]
        f2 = self.fonts(40)
        lines = _wrap(d, defn, f2, W - 220)[:2]
        if len(_wrap(d, defn, f2, W - 220)) > 2:
            lines[-1] = lines[-1].rstrip(".,") + "…"
        for i, line in enumerate(lines):
            d.text((W // 2, top + 498 + i * 50), line, font=f2, fill=(230, 230, 230, 255), anchor="mm")

    def _caption(self, d, chunk, active_idx, y_center):
        words = [w[0].upper() for w in chunk]
        font, size = _fit(d, " ".join(words), self.fonts, self.W - 120, 104)
        stroke = max(5, size // 10)
        space = _text_w(d, " ", font)
        widths = [_text_w(d, w, font, stroke) for w in words]
        x = (self.W - (sum(widths) + space * (len(words) - 1))) // 2
        for i, (w, wd) in enumerate(zip(words, widths)):
            color = self.accent if i == active_idx else WHITE
            d.text((x, y_center), w, font=font, fill=color, anchor="lm",
                   stroke_width=stroke, stroke_fill=BLACK)
            x += wd + space

    def _handle(self, d):
        if self.handle:
            d.text((self.W // 2, self.H - 440), self.handle, font=self.fonts(40),
                   fill=(255, 255, 255, 170), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 170))


def build_overlay(tts: dict, painter: Painter, workdir: Path) -> Path:
    """Render one PNG per visual state and return an ffmpeg concat list that plays them in sync."""
    frames_dir = workdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    reveal = next(s["start"] for s in tts["segments"] if s["kind"] == "word")
    end = tts["duration"]
    chunks = chunk_words(tts["words"])
    # each chunk stays on screen until the next one starts
    windows = [(c[0][1], chunks[i + 1][0][1] if i + 1 < len(chunks) else end, c)
               for i, c in enumerate(chunks)]

    def state_at(t):
        chunk = next((c for s, e, c in windows if s <= t < e), None)
        idx = None
        if chunk:
            idx = next((i for i, (_, ws, we) in enumerate(chunk) if ws <= t < we), None)
        return (t >= reveal, id(chunk) if chunk else None, idx), chunk

    times = {0.0, reveal}
    for c in chunks:
        for _, ws, we in c:
            times.update((ws, we))
    times = sorted(t for t in times if 0 <= t < end)

    lines, prev_key, n = [], None, 0
    for i, t in enumerate(times):
        key, chunk = state_at(t)
        t_next = times[i + 1] if i + 1 < len(times) else end
        if key == prev_key:  # extend previous frame
            last = lines[-1]
            lines[-1] = (last[0], last[1] + (t_next - t))
            continue
        p = frames_dir / f"f{n:04d}.png"
        n += 1
        painter.frame(key[0], chunk, key[2], p)
        lines.append((p, t_next - t))
        prev_key = key

    body = "".join(f"file '{p.as_posix()}'\nduration {d:.3f}\n" for p, d in lines)
    body += f"file '{lines[-1][0].as_posix()}'\n"  # concat demuxer: repeat last file
    listfile = workdir / "overlay.txt"
    listfile.write_text(body)
    return listfile


# ---------------------------------------------------------------- final compose
def background_input(cfg: dict, duration: float, rng: random.Random, theme: dict) -> tuple[list[str], str]:
    v = cfg["video"]
    W, H, fps = v["width"], v["height"], v["fps"]
    clip = pick_random(ASSETS / "gameplay", VIDEO_EXTS, rng)
    dark = v.get("darken_background", 0.15)
    if clip:
        clip_dur = probe_duration(clip)
        if clip_dur > duration + 2:
            start = rng.uniform(0, clip_dur - duration - 1)
            args = ["-ss", f"{start:.2f}", "-t", f"{duration + 0.5:.2f}", "-i", str(clip)]
        else:
            args = ["-stream_loop", "-1", "-t", f"{duration + 0.5:.2f}", "-i", str(clip)]
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,"
              f"fps={fps},eq=brightness={-dark:.2f}:saturation=1.15[bg]")
        print(f"[render] background: {clip.name}")
        return args, vf
    a = theme["accent"].lstrip("#")
    args = ["-f", "lavfi", "-t", f"{duration + 0.5:.2f}", "-i",
            f"gradients=s={W}x{H}:r={fps}:c0=0x0b0b1a:c1=0x{a}:c2=0x10102a:nb_colors=3:speed=0.015:type=radial"]
    vf = f"[0:v]setsar=1,eq=brightness=-0.25:saturation=0.8[bg]"
    print("[render] background: animated gradient (add clips to assets/gameplay/ for gameplay backgrounds)")
    return args, vf


def compose(cfg: dict, tts: dict, overlay_list: Path, theme: dict, rng: random.Random, out: Path) -> Path:
    v = cfg["video"]
    D = tts["duration"]
    bg_args, bg_filter = background_input(cfg, D, rng, theme)
    inputs = [*bg_args, "-f", "concat", "-safe", "0", "-i", str(overlay_list), "-i", str(tts["audio"])]
    music = pick_random(ASSETS / "music", AUDIO_EXTS, rng)
    accent = theme["accent"].lstrip("#")
    filters = [
        bg_filter,
        "[1:v]format=rgba[ov]",
        "[bg][ov]overlay=0:0:format=auto:shortest=0[v1]",
        f"color=c=0x{accent}:s={v['width']}x14:r={v['fps']}:d={D + 0.5:.2f}[bar]",
        f"[v1][bar]overlay=x='-w+w*t/{D:.3f}':y={v['height'] - 14}:eval=frame,format=yuv420p[v]",
    ]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        filters += [
            f"[3:a]volume={v.get('music_volume', 0.1)},afade=t=out:st={max(D - 1.5, 0):.2f}:d=1.5[m]",
            "[2:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]",
        ]
        print(f"[render] music: {music.name}")
    else:
        filters.append("[2:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]")

    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg([
        *inputs, "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-t", f"{D:.3f}", "-r", str(v["fps"]),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out),
    ])
    return out
