"""Decides what the captions should say, based on what happens in the clip.

With an Anthropic API key, Claude looks at frames from the clip, the speech
transcript and the chat around the explosion, and writes:
  - a hook headline for the top of the video
  - short reaction "beats" timed to key moments ("HE MISSED THE JUMP")
  - which words to highlight, the mood, where to crop, and a post caption.

Without a key, a rule-based fallback reads the chat's emotes to pick the mood
and fills in templates.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .transcribe import Word

log = logging.getLogger(__name__)

MOODS = ["funny", "hype", "shock", "rage", "sad", "wholesome"]

# Chat vocabulary per mood (matched case-insensitively against whole tokens).
MOOD_WORDS = {
    "funny": {"kekw", "lul", "lmao", "lmfao", "omegalul", "icant", "lol", "haha", "hahaha", "xd", "😂", "🤣",
              "kekl", "pepelaugh", "lulw", "dead", "💀"},
    "hype": {"pog", "poggers", "pogchamp", "w", "ww", "www", "goat", "hype", "letsgo", "lets", "🔥", "ez",
             "clutch", "insane", "cracked", "huge", "🐐"},
    "shock": {"wtf", "no", "way", "what", "?", "??", "???", "holy", "monkas", "omg", "😱", "😳", "bro", "huh"},
    "rage": {"madge", "bruh", "trash", "l", "ll", "ratio", "😡", "copium", "throw", "threw"},
    "sad": {"f", "rip", "sadge", "😢", "😭", "pain", "nooo", "noooo", "unlucky"},
    "wholesome": {"❤", "❤️", "<3", "aww", "cute", "wholesome", "love", "🥺", "peepohappy"},
}

HOOKS = {
    "funny": "{name} had chat CRYING",
    "hype": "{name} just went CRAZY",
    "shock": "Chat could NOT believe this",
    "rage": "{name} is LIVID",
    "sad": "This hurt to watch",
    "wholesome": "This was too wholesome",
}

EMOJI = {"funny": "😂", "hype": "🔥", "shock": "😱", "rage": "😡", "sad": "💔", "wholesome": "🥹"}


@dataclass
class Beat:
    t: float      # seconds from clip start
    text: str


@dataclass
class Plan:
    hook: str
    mood: str
    beats: list[Beat] = field(default_factory=list)
    emphasis: list[str] = field(default_factory=list)
    crop_focus_x: float = 0.5
    post_caption: str = ""
    source: str = "rules"


# ---------------- rule-based fallback ----------------

def _tokens(text: str) -> list[str]:
    text = text.lower()
    toks = re.findall(r"[a-z0-9<']+|\?+|[^\s\w]", text)
    out = []
    for t in toks:
        out.append(t)
        if re.fullmatch(r"w+", t):
            out.append("w")
    return out


def chat_mood(messages: list[str]) -> tuple[str, Counter]:
    scores: Counter = Counter()
    for m in messages:
        toks = set(_tokens(m))
        if "lets" in toks and "go" in toks:
            toks.add("letsgo")
        for mood, vocab in MOOD_WORDS.items():
            if toks & vocab:
                scores[mood] += 1
    mood = scores.most_common(1)[0][0] if scores else "hype"
    return mood, scores


def rule_plan(meta: dict, words: list[Word]) -> Plan:
    timeline = meta.get("chat_timeline") or []
    texts = [t[2] for t in timeline] or [s.split(": ", 1)[-1] for s in meta.get("chat_sample", [])]
    mood, _ = chat_mood(texts)
    name = meta.get("name") or meta.get("channel", "Streamer")
    offset = float(meta.get("explosion_offset", 30))
    # The most-spammed chat message becomes an on-screen "chat reaction" beat.
    spam = Counter(t.strip().upper() for t in texts if 0 < len(t.strip()) <= 24).most_common(1)
    beats = [Beat(offset + 0.5, f"CHAT: {spam[0][0]}")] if spam else []
    return Plan(hook=HOOKS[mood].format(name=name), mood=mood, beats=beats,
                post_caption=f"{name} {EMOJI[mood]} #gta6 #{meta.get('platform', '')} #clips",
                source="rules")


# ---------------- Claude ----------------

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hook", "mood", "beats", "emphasis", "crop_focus_x", "post_caption"],
    "properties": {
        "hook": {"type": "string", "description": "Headline shown on top for the whole clip. Max 7 words."},
        "mood": {"type": "string", "enum": MOODS},
        "beats": {
            "type": "array",
            "description": "0-3 short reaction captions at key moments.",
            "items": {"type": "object", "additionalProperties": False, "required": ["t", "text"],
                      "properties": {"t": {"type": "number"}, "text": {"type": "string"}}},
        },
        "emphasis": {"type": "array", "items": {"type": "string"},
                     "description": "Up to 6 spoken words worth highlighting."},
        "crop_focus_x": {"type": "number", "description": "0=left edge, 0.5=center, 1=right edge"},
        "post_caption": {"type": "string"},
    },
}

PROMPT = """You are editing a livestream clip into a vertical short (TikTok/Shorts/Reels).
The clip was cut automatically because Twitch/YouTube/Kick chat suddenly exploded.

Streamer: {name} ({platform})
Stream title: {title}
Clip length: {length:.0f}s. Chat exploded at t={offset:.0f}s, so the moment that caused it happened just before that.

Speech transcript (t = seconds from clip start):
{transcript}

Chat around the explosion:
{chat}

The images are frames from the clip, labelled with their timestamps.

Work out what actually happened, then write:
- hook: a punchy headline that makes people stop scrolling, about what happened (not generic). Max 7 words. Use the streamer's name if it helps. No hashtags, no emoji.
- mood: the overall feel of the moment.
- beats: 0-3 short on-screen captions (max 5 words each, no emoji) timed to the key moments you can see or hear, e.g. the moment just before the explosion. Don't repeat the hook. Leave beats empty if the speech captions already tell the story.
- emphasis: words from the transcript worth highlighting (the punchline, names, swear-free key words).
- crop_focus_x: if the video is cropped to a vertical strip, where should its center be so the action stays in frame?
- post_caption: one line to post with the clip, with 3-5 hashtags."""


def _extract_frames(clip: Path, times: list[float], width: int = 640) -> list[tuple[float, str]]:
    frames = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "5", "-f", "mjpeg", "pipe:1"],
                           capture_output=True)
        if r.returncode == 0 and r.stdout:
            frames.append((t, base64.b64encode(r.stdout).decode()))
    return frames


async def claude_plan(clip: Path, meta: dict, words: list[Word], length: float, model: str) -> Plan | None:
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic not installed: using rule-based captions")
        return None
    offset = float(meta.get("explosion_offset", 30))
    times = sorted({max(0.5, offset * 0.4), max(0.5, offset - 6), max(0.5, offset - 2),
                    min(length - 0.5, offset + 2), min(length - 0.5, offset + 8)})
    frames = await asyncio.to_thread(_extract_frames, clip, times)

    transcript = "\n".join(_lines(words)) or "(no speech detected)"
    chat = "\n".join(f"t={t:5.1f}  {u}: {m}" for t, u, m in (meta.get("chat_timeline") or [])[:120]) \
        or "\n".join(meta.get("chat_sample", [])) or "(none)"
    content: list[dict] = []
    for t, b64 in frames:
        content.append({"type": "text", "text": f"Frame at t={t:.1f}s"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    content.append({"type": "text", "text": PROMPT.format(
        name=meta.get("name") or meta.get("channel"), platform=meta.get("platform"),
        title=meta.get("title") or "(unknown)", length=length, offset=offset,
        transcript=transcript, chat=chat)})

    try:
        client = anthropic.AsyncAnthropic()
        resp = await client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # if the model declines, the API retries on a fallback model
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        log.warning("no valid Anthropic API key: using rule-based captions (set ANTHROPIC_API_KEY)")
        return None
    except anthropic.RateLimitError:
        log.warning("Claude rate limited: using rule-based captions for this clip")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Claude request failed (%s): using rule-based captions", e.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("couldn't reach the Claude API: using rule-based captions")
        return None
    except (anthropic.AnthropicError, TypeError) as e:  # TypeError: no API key configured at all
        log.warning("Claude unavailable (%s): using rule-based captions", str(e).split(".")[0])
        return None
    if resp.stop_reason != "end_turn":
        log.warning("Claude stopped with %s: using rule-based captions", resp.stop_reason)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Claude returned unparseable JSON: using rule-based captions")
        return None
    mood = d.get("mood") if d.get("mood") in MOODS else "hype"
    return Plan(
        hook=d.get("hook", "").strip() or HOOKS[mood].format(name=meta.get("name", "")),
        mood=mood,
        beats=[Beat(float(b["t"]), b["text"]) for b in d.get("beats", [])[:3]
               if 0 <= float(b.get("t", -1)) < length and b.get("text")],
        emphasis=[w.lower() for w in d.get("emphasis", [])][:6],
        crop_focus_x=min(1.0, max(0.0, float(d.get("crop_focus_x", 0.5)))),
        post_caption=d.get("post_caption", ""),
        source="claude",
    )


def _lines(words: list[Word]) -> list[str]:
    lines, cur, start = [], [], 0.0
    for w in words:
        if not cur:
            start = w.start
        cur.append(w.text)
        if w.text.endswith((".", "!", "?")) or len(cur) >= 14:
            lines.append(f"t={start:5.1f}  {' '.join(cur)}")
            cur = []
    if cur:
        lines.append(f"t={start:5.1f}  {' '.join(cur)}")
    return lines
