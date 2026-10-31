"""CLI entry point.

  python -m shortsbot wotd                 # render today's word-of-the-day Short into out/
  python -m shortsbot wotd --upload        # ...and upload it to YouTube
  python -m shortsbot wotd --batch 7 --upload --schedule-hours 24
                                           # render a week and schedule one per day
  python -m shortsbot clips --upload --schedule-hours 8
                                           # cut highlights from assets/vods/ and schedule them
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import tempfile
from pathlib import Path

from . import clips as clipmod
from . import content, render, tts, youtube
from .common import (ASSETS, OUT, VIDEO_EXTS, find_font, list_files, load_config, load_state,
                     require_ffmpeg, save_json, save_state)


def _rfc3339(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _publish_times(n: int, every_hours: float | None, first_at: str | None) -> list[str | None]:
    if not every_hours:
        return [None] * n
    if first_at:
        base = dt.datetime.fromisoformat(first_at.replace("Z", "+00:00"))
    else:
        base = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    return [_rfc3339(base + dt.timedelta(hours=every_hours * i)) for i in range(n)]


def cmd_wotd(args) -> int:
    require_ffmpeg()
    cfg = load_config()
    state = load_state()
    font = find_font()
    can_upload = args.upload and youtube.configured()
    if args.upload and not can_upload:
        print("[wotd] --upload given but YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN not set; "
              "rendering only", file=sys.stderr)
    times = _publish_times(args.batch, args.schedule_hours, args.first_publish_at)
    today = dt.date.today().isoformat()

    for n in range(args.batch):
        rng = random.Random(f"{today}-{len(state['used_words'])}-{args.seed}")
        word = content.pick_word(cfg, state["used_words"], rng,
                                 prefer_claude=False if args.no_claude else None)
        day = len(state["used_words"]) + 1
        themes = cfg["themes"]
        theme = themes[day % len(themes)]  # rotate looks so uploads aren't identical
        print(f"[wotd] #{day}: {word['word']} (from {word['source']}, theme {theme['name']})")

        script = content.build_script(word, cfg, rng)
        slug = word["word"].lower().replace(" ", "-")
        out = OUT / f"{today}_{day:04d}_{slug}.mp4"
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            audio = tts.synthesize(script, cfg["voice"], cfg.get("voice_rate", "+0%"),
                                   cfg.get("pause_between_segments", 0.25), work)
            painter = render.Painter(cfg["video"]["width"], cfg["video"]["height"], render.Fonts(font),
                                     theme, word, day, cfg.get("channel_handle", ""))
            overlay = render.build_overlay(audio, painter, work)
            render.compose(cfg, audio, overlay, theme, rng, out)
        meta = content.build_metadata(word, cfg)
        save_json(out.with_suffix(".json"), {**meta, "word": word, "duration": audio["duration"]})
        print(f"[wotd] rendered {out}  ({audio['duration']:.1f}s)")

        if args.dry_run:
            continue
        record = {"date": today, "word": word["word"], "file": out.name}
        if can_upload:
            if not audio["real_voice"]:
                print("[wotd] refusing to upload: voice synthesis failed (silent preview)", file=sys.stderr)
                return 2
            record["youtube_id"] = youtube.upload(out, meta, cfg["youtube"], times[n])
            record["publish_at"] = times[n]
        state["used_words"].append(word["word"])
        state["uploads"].append(record)
        save_state(state)
    return 0


def cmd_clips(args) -> int:
    require_ffmpeg()
    cfg = load_config()
    state = load_state()
    font = find_font()
    rng = random.Random(args.seed)
    vods = [v for v in list_files(Path(args.vods), VIDEO_EXTS) if v.name not in state["processed_vods"]]
    if not vods:
        print(f"[clips] no new recordings in {args.vods}")
        return 0
    can_upload = args.upload and youtube.configured()
    made = []
    with tempfile.TemporaryDirectory() as tmp:
        for vod in vods:
            accent = rng.choice(cfg["themes"])["accent"]
            print(f"[clips] analysing {vod.name}")
            made += clipmod.make_clips(vod, cfg, font, accent, OUT / "clips", Path(tmp), rng)
            if not args.dry_run:
                state["processed_vods"].append(vod.name)

    c = cfg["clips"]
    times = _publish_times(len(made), args.schedule_hours, args.first_publish_at)
    for clip, when in zip(made, times):
        meta = {
            "title": f"{clip['hook']} #shorts"[:100],
            "description": f"{clip['hook']}\n\n" + " ".join(c.get("default_hashtags", [])),
            "tags": c.get("default_tags", []),
            "category_id": c.get("category_id", "20"),
        }
        save_json(clip["path"].with_suffix(".json"), meta)
        if can_upload and not args.dry_run:
            vid = youtube.upload(clip["path"], meta, cfg["youtube"], when)
            state["uploads"].append({"date": dt.date.today().isoformat(), "clip": clip["path"].name,
                                     "youtube_id": vid, "publish_at": when})
    if not args.dry_run:
        save_state(state)
    print(json.dumps([str(c["path"]) for c in made], indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="shortsbot")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--upload", action="store_true", help="upload to YouTube (needs YT_* env vars)")
        sp.add_argument("--dry-run", action="store_true", help="render only; don't touch state.json")
        sp.add_argument("--schedule-hours", type=float, help="schedule uploads N hours apart (private until then)")
        sp.add_argument("--first-publish-at", help="RFC3339 time for the first scheduled upload")
        sp.add_argument("--seed", default="0")

    w = sub.add_parser("wotd", help="word-of-the-day Short")
    common(w)
    w.add_argument("--batch", type=int, default=1, help="how many videos to make")
    w.add_argument("--no-claude", action="store_true", help="only use data/words.json")
    w.set_defaults(func=cmd_wotd)

    c = sub.add_parser("clips", help="gameplay highlight Shorts from your recordings")
    common(c)
    c.add_argument("--vods", default=str(ASSETS / "vods"))
    c.set_defaults(func=cmd_clips)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
