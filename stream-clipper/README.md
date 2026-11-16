# Stream Clipper

Watches livestream chat and saves a clip whenever chat explodes. Each clip
starts **30 seconds before** the explosion, so you get the moment that set
chat off, not just the reaction.

By default it finds the **10 biggest GTA 6 streams** across **Twitch, YouTube
and Kick**, re-ranks them every 5 minutes, and swaps channels in and out as
the rankings change.

```
13:02:11 INFO    top 10 for 'Grand Theft Auto VI': twitch:kaicenat(212,904), kick:adinross(98,311), ...
13:14:37 INFO    🔥 twitch:kaicenat chat exploded: 412.6 msg/s vs 61.2 normal (x6.7, z=18.3)
13:14:58 INFO    🎬 saved clips/twitch_kaicenat_20261119-131434.mp4
```

## How it works

1. **Discovery.** Asks each platform's API for live streams of the game and keeps the top 10 by viewers.
2. **Rolling buffer.** For each stream, `streamlink` pipes video into `ffmpeg`, which writes 2-second
   pieces to `buffer/`. Anything older than about 2 minutes is deleted, so disk use stays small.
3. **Chat.** Reads chat live: Twitch over anonymous IRC, Kick over its Pusher websocket, YouTube
   through `chat-downloader`. Reading chat needs no keys.
4. **Explosion detection.** Every second it compares the last 5 seconds of chat with the previous
   5 minutes. A clip fires when chat is at least **3× normal** *and* far outside normal variation.
   Each chatter counts once per second, so one spammer can't trigger it. "Normal" is learned per
   channel, so 60 msg/s on a huge channel and 2 msg/s on a small one both work.
5. **Clip.** It finds where the surge began, waits 20 seconds for the aftermath, then joins the
   pieces from 30 s before the surge to 20 s after into one `.mp4` (no re-encoding, so it's fast).
   A `.json` file next to it holds the stats and a sample of what chat was saying.

## Setup

You need Python 3.11+ and **ffmpeg** (`brew install ffmpeg`, `winget install ffmpeg`, `apt install ffmpeg`).

```bash
cd stream-clipper
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.toml config.toml                   # then add your keys
```

API keys are only used to find the top streams. Each one is free:

| Platform | Where | Notes |
| --- | --- | --- |
| Twitch | [dev.twitch.tv/console/apps](https://dev.twitch.tv/console/apps) | Register an app, client type "Confidential", any redirect URL (`http://localhost`) |
| YouTube | Google Cloud console → enable **YouTube Data API v3** → Credentials → API key | 10,000 free quota units a day; a search costs 100, so it re-checks every 15 min |
| Kick | [kick.com/settings/developer](https://kick.com/settings/developer) | Create an app, copy the client ID and secret |

A platform without keys is skipped. You can also list channels by hand in `always_track`.

## Usage

```bash
python -m clipper discover                    # who's in the top 10 right now?
python -m clipper run                         # track the top 10 and clip
python -m clipper watch twitch:kaicenat kick:adinross https://www.youtube.com/watch?v=VIDEO_ID
python -m clipper simulate                    # watch the detector work on fake chat
```

**Test before release day:** GTA 6 isn't out yet, so try it on something live right now:

```bash
python -m clipper discover --game "Just Chatting"
python -m clipper run --game "Grand Theft Auto V"
```

A status table prints every 30 seconds:

```
channel                          video   chat/s  normal clips
twitch:kaicenat                  live     58.4    61.2     3
kick:adinross                    live     22.0    19.7     1
```

Clips land in `clips/`, with `clips/index.jsonl` as a running log of every clip.

## Tuning

Everything is in `config.toml`:

- **Too many clips?** Raise `multiplier` (e.g. 4.0) or `min_zscore`, or lengthen `cooldown`.
- **Missing moments?** Lower `multiplier` to 2.5.
- **Clips start too late?** Raise `chat_delay`. Viewers react a few seconds after they see something,
  and some streamers run a stream delay.
- **Disk/bandwidth:** 10 streams at `best` is roughly 60–80 Mbit/s down. Use `quality = "720p"` if your
  connection can't keep up.

## Caveats

- **Twitch and Kick may not have a "Grand Theft Auto VI" category on day one** (or may name it
  differently). Run `discover` on launch day; if the name differs, change `game`, or set
  `[kick] category_id`.
- **Kick:** finding a chat room uses `kick.com/api/v2/channels/<slug>`, which Cloudflare sometimes
  blocks. If Kick chat won't connect, find the chatroom id in your browser (open that URL) and
  track it as `kick:slug#123456`.
- **YouTube** chat reading uses `chat-downloader`, which follows YouTube's page format. If YouTube
  changes it, run `pip install -U chat-downloader`.
- Clips are other people's content. Check each platform's terms and credit the streamer if you post them.

## Tests

```bash
python -m pytest
```

Includes an end-to-end test that streams an ffmpeg test pattern, fakes a chat explosion, and checks
that the saved clip has the right length and lead-in.
