# shortsbot: automated faceless Shorts

Two **separate** content formats, each producing 1080×1920 vertical videos ready for
YouTube Shorts, TikTok, Instagram Reels and Facebook Reels. They never mix: pick one for your
channel, or run each on its own channel.

| Engine | What it makes | Runs |
|---|---|---|
| `wotd` | **Word of the day** with a hook, AI voice, word-by-word captions, word card and progress bar on an animated colour background | Daily on GitHub Actions, fully hands-off. Needs no footage |
| `clips` | **Gameplay highlights**: finds the hype moments in your long recordings by audio spikes, cuts 30 s vertical clips with a hook banner | On your PC (recordings are too big for git), schedules a week of uploads at once |

**Word of the day** is the fully automatic one: nothing to supply, posts itself every day.
**Gameplay clips** depend on you recording new gameplay regularly. If you run both, use two
channels (see "Running clips on a second channel" below) so each channel's audience gets one
consistent format; mixing niches on one channel confuses the algorithm and your subscribers.

---

## How a word-of-the-day video is built

```
 0–3 s   HOOK        "There's a word for throwing something out a window."   ← curiosity, word NOT revealed
 3–6 s   REVEAL      "The word is: Defenestration."  + big word card appears
 6–14 s  MEANING     part of speech + plain-English definition
14–22 s  EXAMPLE     a modern, funny example sentence
22–28 s  CTA / LOOP  "Defenestration. Use it in a sentence in the comments…"
```

* Word-level captions with the spoken word highlighted (most viewers watch on mute)
* Progress bar along the bottom (people stay longer when they can see the end)
* Slow-moving gradient background in one of 5 colour themes that rotate daily,
  so uploads don't all look the same
* Loudness-normalised to −14 LUFS (platform standard)
* Words come from **Claude** (fresh, never repeated, with title/description/tags), or from
  the 40-word bank in `data/words.json` if no API key is set

---

## Setup (about 30 minutes, once)

### 1. Personalise
Change `channel_name` / `channel_handle` in `config.json`.
Optional: music from the YouTube Audio Library in `assets/music/`, a bold font in `assets/fonts/`.

### 2. YouTube API access
1. [Google Cloud Console](https://console.cloud.google.com/) → new project → enable **YouTube Data API v3**.
2. **OAuth consent screen** → External → add your Google account as a test user, then
   **Publish app** (set it to "In production"). In "Testing" mode the token dies after 7 days and
   the daily job will stop.
3. **Credentials** → Create OAuth client ID → **Desktop app** → download the JSON.
4. On your computer:
   ```bash
   pip install google-auth-oauthlib
   python tools/get_youtube_token.py ~/Downloads/client_secret_XXXX.json
   ```
   Sign in as the channel owner. It prints `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.
5. **Important:** videos uploaded through the API by an *unaudited* Google Cloud project are
   locked to **private**. Submit the free
   [YouTube API Services audit form](https://support.google.com/youtube/contact/yt_api_form)
   for your project (say it's for uploading to your own channel). Until it's approved,
   flip each video to public by hand in YouTube Studio, or post manually from the artifact.

### 3. GitHub secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Needed for |
|---|---|
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` | uploading |
| `ANTHROPIC_API_KEY` | fresh AI-written words (optional; costs well under a cent per video) |

### 4. Turn it on
Actions tab → enable workflows → **Daily word-of-the-day Short** → *Run workflow* to test.
After that it runs every day at the time in `.github/workflows/daily-shorts.yml`. To post more
than once a day, add another `- cron:` line. Each run also saves the MP4 as a downloadable
artifact for 14 days.

---

## Running locally

```bash
cd shorts
pip install -r requirements.txt          # plus ffmpeg on your PATH
python -m shortsbot wotd --dry-run       # renders to out/, doesn't mark the word used
python -m shortsbot wotd --upload        # render + upload now

# render a week of videos and schedule one per day starting tomorrow 15:00 UTC
python -m shortsbot wotd --batch 7 --upload --schedule-hours 24 --first-publish-at 2026-11-01T15:00:00Z

# gameplay highlights: put long recordings in assets/vods/, then
python -m shortsbot clips --dry-run                       # just cut clips into out/clips/
python -m shortsbot clips --upload --schedule-hours 8     # cut + schedule one every 8 h
```

`SHORTS_TTS=silent` renders with silent audio and estimated timings (layout previews offline).

### Running clips on a second channel
By default both tools upload to the channel behind `YT_CLIENT_ID` / `YT_CLIENT_SECRET` /
`YT_REFRESH_TOKEN`. To send clips somewhere else, run `tools/get_youtube_token.py` again while
signed in to the second channel and set the results as `YT_CLIPS_CLIENT_ID`,
`YT_CLIPS_CLIENT_SECRET`, `YT_CLIPS_REFRESH_TOKEN` (environment variables on your PC, since
clips run locally). When those are set, `clips` uses them automatically.

---

## Posting to TikTok, Instagram and Facebook

YouTube uploads are built in. For the others, the simple and reliable route is a cross-poster that
watches your YouTube channel and re-posts each new Short natively, without the YouTube watermark:
**Repurpose.io**, **Metricool**, or **Buffer** (all have plans around $10–30/month and handle
TikTok/Reels/Facebook posting through those platforms' official APIs). Direct API posting
is possible later, but TikTok and Meta both require an app review before API posts can be public.

---

## Getting to monetisation: what matters

**Thresholds (YouTube Partner Program):** 1,000 subscribers **and** either 4,000 public watch hours
in 12 months or **10 million Shorts views in 90 days**. TikTok's Creator Rewards needs 10k followers
and pays only for videos over 1 minute. For this niche, views come from Shorts, and money mostly comes
from long-form, sponsors and affiliate links once you have an audience.

**The biggest risk to an automated channel is YouTube's "inauthentic content" policy** (formerly
"repetitious content"). It demonetises channels that publish mass-produced, near-identical videos.
This project already varies colour themes, hooks and CTAs, but you should also:

* **Review videos before they go public** for the first few weeks (`--schedule-hours` gives you a
  window to watch and delete bad ones). AI occasionally gets a pronunciation or definition wrong.
* Add a human touch the bot can't: pin a comment with a bonus fact, reply to commenters' sentences,
  run a weekly "quiz" video of the last 7 words.
* Keep **AI-voice disclosure** honest: set `contains_synthetic_media` to `true` in `config.json`
  if you change the content to anything that could look like a real person or real event.
* Footage: never use other creators' gameplay, streams or movie clips without permission. Three
  copyright strikes delete the channel. For the clipping niche, the legitimate route is your own
  gameplay or official **streamer clipping programs** (many streamers pay clippers per view).

**Growth levers to test** (change one thing at a time, compare after ~7 videos):
1. Hook wording: "There's a word for…" vs. "Only 1% of people know…" vs. a question.
2. Posting time: try 2–3 slots per day once things are stable (add cron lines).
3. Colour themes and fonts: edit `themes` in `config.json`, drop a font in `assets/fonts/`.
4. Length: 20–30 s loops get more replays; 60 s+ is needed for TikTok payouts.
5. Look at YouTube Studio → *Viewed vs. swiped away*. Under ~60% viewed means the first
   second needs work.

Nobody can guarantee a video goes viral. What you control is consistency (this bot), the first
2 seconds (the hook), and not getting flagged (variety, honest content, licensed footage).

---

## Files

```
shorts/
  config.json            channel name, voice, themes, CTAs, YouTube defaults, clip settings
  data/words.json        fallback word bank (add your own)
  data/state.json        words already posted + upload log (committed by the workflow)
  assets/vods/           long recordings for the clips engine (git-ignored)
  assets/music/ fonts/   optional
  shortsbot/             the code (content, tts, render, clips, youtube, CLI)
  tools/get_youtube_token.py
```
