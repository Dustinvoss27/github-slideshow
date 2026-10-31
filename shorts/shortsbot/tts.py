"""Text-to-speech with word-level timestamps (for karaoke-style captions).

Uses Microsoft Edge's free neural voices via the `edge-tts` package. If the service is
unreachable (or SHORTS_TTS=silent), it falls back to silent audio with estimated word
timings so you can still preview layouts offline.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from .common import probe_duration, run_ffmpeg

TICKS = 10_000_000  # edge-tts offsets are in 100ns units


async def _edge(text: str, voice: str, rate: str, mp3: Path) -> list[tuple[str, float, float]]:
    import edge_tts

    words: list[tuple[str, float, float]] = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(mp3, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append((chunk["text"], start, start + chunk["duration"] / TICKS))
    return words


def _estimate(text: str) -> tuple[list[tuple[str, float, float]], float]:
    words, t = [], 0.15
    for w in text.split():
        d = 0.12 + 0.055 * len(re.sub(r"\W", "", w))
        words.append((w, t, t + d))
        t += d + (0.25 if w[-1] in ".,:;!?" else 0.04)
    return words, t + 0.2


def _attach_punctuation(text: str, words: list[tuple[str, float, float]]):
    """Edge returns bare words; re-attach trailing punctuation from the source text for captions."""
    tokens = text.split()
    out, ti = [], 0
    for w, s, e in words:
        while ti < len(tokens) and w.lower() not in tokens[ti].lower():
            ti += 1
        out.append((tokens[ti] if ti < len(tokens) else w, s, e))
        ti += 1
    return out


def synthesize(segments: list[dict], voice: str, rate: str, pause: float, workdir: Path) -> dict:
    """Speak each segment, then concatenate. Returns audio path, per-segment timings, word timings."""
    workdir.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get("SHORTS_TTS", "edge")
    timeline, all_words, wavs, cursor = [], [], [], 0.0

    for i, seg in enumerate(segments):
        wav = workdir / f"seg{i}.wav"
        words = None
        if mode != "silent":
            mp3 = workdir / f"seg{i}.mp3"
            try:
                words = asyncio.run(_edge(seg["text"], voice, rate, mp3))
                if not mp3.exists() or mp3.stat().st_size == 0:
                    raise RuntimeError("empty audio")
                run_ffmpeg(["-i", str(mp3), "-af", f"apad=pad_dur={pause}", "-ar", "48000", "-ac", "2", str(wav)])
                words = _attach_punctuation(seg["text"], words) if words else _estimate(seg["text"])[0]
            except Exception as e:  # network blocked, service down, etc.
                print(f"[tts] edge-tts failed ({e!r}); falling back to silent preview audio", file=sys.stderr)
                mode = "silent"
                words = None
        if words is None:
            words, dur = _estimate(seg["text"])
            run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{dur + pause:.3f}", str(wav)])

        dur = probe_duration(wav)
        timeline.append({**seg, "start": cursor, "end": cursor + dur})
        all_words.extend((w, cursor + s, cursor + e) for w, s, e in words)
        wavs.append(wav)
        cursor += dur

    listfile = workdir / "audio_list.txt"
    listfile.write_text("".join(f"file '{w.name}'\n" for w in wavs))
    narration = workdir / "narration.wav"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(narration)])
    return {"audio": narration, "duration": cursor, "segments": timeline, "words": all_words,
            "real_voice": mode != "silent"}
