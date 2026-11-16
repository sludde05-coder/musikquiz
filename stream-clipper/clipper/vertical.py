"""Turns a saved 16:9 clip into a captioned 9:16 video for phones.

  layout "blur": the full frame centered, over a blurred zoomed copy of itself
                 (nothing gets cut off; captions sit above and below the video)
  layout "crop": a vertical slice of the frame, positioned where the action is
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from .captions import build_ass
from .config import VerticalConfig
from .director import Plan, claude_plan, rule_plan
from .transcribe import transcribe

log = logging.getLogger(__name__)
_slots: asyncio.Semaphore | None = None


def probe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def filter_graph(layout: str, focus_x: float) -> str:
    if layout == "crop":
        return (f"[0:v]scale=-2:1920,crop=1080:1920:x='(iw-1080)*{focus_x:.3f}':y=0,"
                f"setsar=1,ass=captions.ass[v]")
    return ("[0:v]split[a][b];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "gblur=sigma=40,eq=brightness=-0.12:saturation=1.2[bg];"
            "[b]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,ass=captions.ass[v]")


async def render_vertical(clip: Path, cfg: VerticalConfig, out: Path | None = None) -> Path | None:
    """Make <clip>_vertical.mp4 next to the clip and add the caption plan to its .json."""
    global _slots
    if _slots is None:
        _slots = asyncio.Semaphore(max(1, cfg.max_parallel))
    async with _slots:  # transcription + encoding are CPU heavy; don't run 10 at once
        meta_path = clip.with_suffix(".json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        length = await asyncio.to_thread(probe_duration, clip)

        words = await asyncio.to_thread(transcribe, clip, cfg.whisper_model) if cfg.speech_captions else []
        plan: Plan | None = None
        if cfg.ai_captions:
            plan = await claude_plan(clip, meta, words, length, cfg.ai_model)
        plan = plan or rule_plan(meta, words)
        log.info("✍️  %s: \"%s\" (%s, %s, %d words, %d beats)", clip.name, plan.hook, plan.mood,
                 plan.source, len(words), len(plan.beats))

        out = out or clip.with_name(clip.stem + "_vertical.mp4")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "captions.ass").write_text(
                build_ass(plan, words, length, cfg.layout, cfg.font), encoding="utf-8")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip.resolve()),
                "-filter_complex", filter_graph(cfg.layout, plan.crop_focus_x),
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", cfg.preset, "-crf", str(cfg.crf), "-pix_fmt", "yuv420p",
                "-r", "30", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out.resolve()),
                cwd=tmp, stderr=asyncio.subprocess.PIPE)
            _, err = await proc.communicate()
        if proc.returncode != 0:
            log.error("vertical render failed for %s: %s", clip.name, err.decode(errors="replace")[-600:])
            return None

        meta["vertical"] = out.name
        meta["captions"] = {**asdict(plan), "transcript": " ".join(w.text for w in words)}
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        log.info("📱 saved %s", out)
        return out
