"""Builds an .ass subtitle file (styled, animated captions that ffmpeg burns in).

Three layers on a 1080x1920 canvas:
  hook     – headline on a box at the top, whole clip
  speech   – 1-3 words at a time, the word being spoken pops in the mood color
  beats    – big reaction text at key moments
"""
from __future__ import annotations

import re

from .director import Plan
from .transcribe import Word

W, H = 1080, 1920

# Mood accent colors as (R, G, B).
COLORS = {
    "funny": (255, 214, 0),
    "hype": (57, 255, 20),
    "shock": (255, 59, 48),
    "rage": (255, 120, 0),
    "sad": (77, 163, 255),
    "wholesome": (255, 105, 180),
}

# Screen positions per layout: (hook_y, speech_y, beat_y)
POSITIONS = {"blur": (600, 1400, 1660), "crop": (200, 1380, 760)}

_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def ass_color(rgb: tuple[int, int, int], alpha: int = 0) -> str:
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def clean(text: str) -> str:
    # Subtitle renderers draw color emoji as empty boxes, and braces are ASS markup.
    text = _EMOJI.sub("", text)
    return " ".join(re.sub(r"[{}\\]", "", text).split())


def ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def group_words(words: list[Word], max_words: int = 3, max_gap: float = 0.6) -> list[list[Word]]:
    groups: list[list[Word]] = []
    for w in words:
        g = groups[-1] if groups else None
        if (g is None or len(g) >= max_words or w.start - g[-1].end > max_gap
                or g[-1].text.endswith((".", "!", "?", ","))):
            groups.append([w])
        else:
            g.append(w)
    return groups


def build_ass(plan: Plan, words: list[Word], length: float, layout: str = "blur",
              font: str = "Arial") -> str:
    accent = COLORS.get(plan.mood, COLORS["hype"])
    hook_y, speech_y, beat_y = POSITIONS.get(layout, POSITIONS["blur"])
    white, black = ass_color((255, 255, 255)), ass_color((0, 0, 0))
    acc = ass_color(accent)
    box = ass_color((0, 0, 0), alpha=0x30)

    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Hook,{font},70,{white},{white},{box},{box},-1,0,0,0,100,100,0,0,3,18,0,2,90,90,0,1",
        f"Style: Speech,{font},92,{white},{white},{black},{black},-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1",
        f"Style: Beat,{font},104,{acc},{acc},{black},{black},-1,0,0,0,100,100,2,0,1,9,4,5,60,60,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    hook = clean(plan.hook).upper()
    if hook:
        out.append(f"Dialogue: 2,{ts(0)},{ts(length)},Hook,,0,0,0,,"
                   f"{{\\an2\\pos(540,{hook_y})\\fad(250,0)}}{hook}")

    emphasis = {e.lower().strip(".,!?") for e in plan.emphasis}
    for group in group_words(words):
        g_end = group[-1].end + 0.15
        for i, w in enumerate(group):
            start = w.start
            end = group[i + 1].start if i + 1 < len(group) else g_end
            parts = []
            for j, other in enumerate(group):
                txt = clean(other.text).upper()
                key = other.text.lower().strip(".,!?\"'")
                if j == i:
                    parts.append(f"{{\\c{acc}\\fscx112\\fscy112}}{txt}{{\\r}}")
                elif key in emphasis:
                    parts.append(f"{{\\c{acc}}}{txt}{{\\r}}")
                else:
                    parts.append(txt)
            pop = "\\fscx85\\fscy85\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            out.append(f"Dialogue: 1,{ts(start)},{ts(end)},Speech,,0,0,0,,"
                       f"{{\\an5\\pos(540,{speech_y}){pop}}}{' '.join(parts)}")

    for b in plan.beats:
        text = clean(b.text).upper()
        if not text:
            continue
        out.append(f"Dialogue: 3,{ts(b.t)},{ts(min(length, b.t + 1.8))},Beat,,0,0,0,,"
                   f"{{\\an5\\pos(540,{beat_y})\\frz-3\\fscx40\\fscy40"
                   f"\\t(0,120,\\fscx115\\fscy115)\\t(120,220,\\fscx100\\fscy100)\\fad(0,200)}}{text}")
    return "\n".join(out) + "\n"
