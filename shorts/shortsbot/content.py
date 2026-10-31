"""Pick (or generate) today's word and turn it into a narration script."""
from __future__ import annotations

import json
import os
import random
import sys

from .common import DATA, load_json

WORD_FIELDS = ["word", "pronunciation", "part_of_speech", "definition", "example", "hook"]

WORD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": WORD_FIELDS + ["title", "description", "tags"],
    "properties": {
        "word": {"type": "string"},
        "pronunciation": {"type": "string"},
        "part_of_speech": {"type": "string"},
        "definition": {"type": "string"},
        "example": {"type": "string"},
        "hook": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM_PROMPT = """You write scripts for a vertical short-form "word of the day" channel \
(YouTube Shorts / TikTok / Reels). Viewers are teens and adults who scroll fast.

Pick ONE real English word (or a loanword commonly listed in English dictionaries) that is \
surprising, fun to say, or names a feeling people recognise but can't name. Avoid slurs, \
sexual terms, and anything unsuitable for a general audience. Accuracy matters: the definition \
must match what major dictionaries say.

Field rules:
- pronunciation: simple respelling with the stressed syllable in CAPS, e.g. "seh-REN-dih-pih-tee". No IPA.
- part_of_speech: noun, verb, adjective, adverb...
- definition: plain language, at most 18 words, no leading "a word for".
- example: one vivid, modern sentence (gaming, internet, school, work life are great), at most 20 words.
- hook: the first thing viewers hear. At most 12 words. Must create curiosity or recognition \
WITHOUT revealing the word. Styles that work: "There's a word for <relatable thing>.", \
"You've felt this but never knew the word.", "Only 1 in 10 people know this word." Don't use clickbait that the video doesn't pay off.
- title: at most 60 characters, curiosity-driven, may include the word, no hashtags.
- description: 1-2 sentences, then the definition. No hashtags (they are added later).
- tags: 6-10 lowercase search tags."""


def _bank() -> list[dict]:
    return load_json(DATA / "words.json", [])


def from_bank(used: set[str], rng: random.Random) -> dict | None:
    fresh = [w for w in _bank() if w["word"].lower() not in used]
    if not fresh:
        return None
    return dict(rng.choice(fresh))


def from_claude(used: set[str], model: str) -> dict | None:
    """Ask Claude for a brand-new word. Returns None (caller falls back) on any problem."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    avoid = ", ".join(sorted(used)) or "(none yet)"
    try:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": WORD_SCHEMA},
            },
            # Route to a fallback model automatically if the request is declined.
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
            messages=[{
                "role": "user",
                "content": f"Write today's word. Do NOT use any of these already-posted words: {avoid}",
            }],
        )
    except anthropic.APIConnectionError as e:
        print(f"[content] Claude unreachable ({e}); using word bank", file=sys.stderr)
        return None
    except anthropic.RateLimitError as e:
        print(f"[content] Claude rate limited ({e}); using word bank", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"[content] Claude API error {e.status_code}: {e.message}; using word bank", file=sys.stderr)
        return None

    if response.stop_reason != "end_turn":
        print(f"[content] Claude stopped with {response.stop_reason}; using word bank", file=sys.stderr)
        return None
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("[content] Claude returned invalid JSON; using word bank", file=sys.stderr)
        return None
    if data.get("word", "").lower() in used or not all(data.get(k) for k in WORD_FIELDS):
        return None
    data["source"] = "claude"
    return data


def pick_word(cfg: dict, used_words: list[str], rng: random.Random, prefer_claude: bool | None = None) -> dict:
    used = {w.lower() for w in used_words}
    use_claude = cfg.get("use_claude", True) if prefer_claude is None else prefer_claude
    word = from_claude(used, cfg.get("claude_model", "claude-opus-5-5")) if use_claude else None
    if word is None:
        word = from_bank(used, rng)
        if word is not None:
            word["source"] = "bank"
    if word is None:
        raise RuntimeError(
            "Word bank exhausted and Claude unavailable. Add words to data/words.json "
            "or set ANTHROPIC_API_KEY."
        )
    return word


def build_script(word: dict, cfg: dict, rng: random.Random) -> list[dict]:
    """Narration segments. Each segment is spoken separately so we know exact timings."""
    pos = word["part_of_speech"].strip().lower()
    article = "an" if pos[:1] in "aeiou" else "a"
    cta = rng.choice(cfg.get("cta_lines") or ["Follow for a new word every day."])
    return [
        {"kind": "hook", "text": word["hook"]},
        {"kind": "word", "text": f"The word is: {word['word']}."},
        {"kind": "definition", "text": f"It's {article} {pos} meaning {word['definition'].rstrip('.')}."},
        {"kind": "example", "text": f"Like this: {word['example']}"},
        {"kind": "cta", "text": f"{word['word']}. {cta}"},
    ]


def build_metadata(word: dict, cfg: dict) -> dict:
    yt = cfg.get("youtube", {})
    title = word.get("title") or word["hook"]
    title = title[:90]
    if "#shorts" not in title.lower():
        title = f"{title} #shorts"
    desc_lines = [
        word.get("description") or word["hook"],
        "",
        f"{word['word']} ({word['pronunciation']}) — {word['part_of_speech']}",
        f"Meaning: {word['definition']}",
        f"Example: {word['example']}",
        "",
        "New word every day. Follow so you don't miss one.",
        "",
        " ".join(yt.get("default_hashtags", []) + [f"#{word['word'].replace(' ', '').replace('-', '').lower()}"]),
    ]
    tags = list(dict.fromkeys([word["word"].lower(), *word.get("tags", []), *yt.get("default_tags", [])]))
    return {
        "title": title[:100],
        "description": "\n".join(desc_lines)[:4900],
        "tags": tags[:30],
        "category_id": yt.get("category_id", "27"),
    }
