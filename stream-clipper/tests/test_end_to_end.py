"""Full pipeline with a fake stream (ffmpeg test pattern) and fake chat."""
import asyncio
import json
import subprocess
import time
from pathlib import Path

import aiohttp

from clipper.config import Config
from clipper.detector import DetectorConfig
from clipper.models import ChatMessage, Stream
from clipper.session import ChannelSession

FAKE_STREAM = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
               "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30",
               "-f", "lavfi", "-i", "sine=frequency=440",
               "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
               "-c:a", "aac", "-f", "mpegts", "pipe:1"]


def duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip())


async def fake_chat(explode_at: float):
    i = 0
    while True:
        now = time.time()
        burst = explode_at <= now < explode_at + 6
        for _ in range(40 if burst else 2):
            i += 1
            yield ChatMessage(f"user{i}", "OMEGALUL" if burst else "hi", time.time())
        await asyncio.sleep(1)


def test_clip_saved_with_preroll(tmp_path):
    cfg = Config()
    cfg.detector = DetectorConfig(warmup=10, short_window=3, baseline_window=60)
    cfg.clips.output_dir = str(tmp_path / "clips")
    cfg.clips.buffer_dir = str(tmp_path / "buf")
    cfg.clips.pre_roll, cfg.clips.post_roll, cfg.clips.segment_seconds = 8, 4, 1

    async def go():
        async with aiohttp.ClientSession() as http:
            st = Stream("twitch", "fake", "fake://", display_name="Fake")
            sess = ChannelSession(st, cfg, http, source_cmd=FAKE_STREAM, chat=fake_chat(time.time() + 18))
            sess.start()
            deadline = time.time() + 60
            while sess.clips_saved == 0 and time.time() < deadline:
                await asyncio.sleep(1)
            await sess.stop()
            return sess

    sess = asyncio.run(go())
    assert sess.clips_saved == 1
    clips = list((tmp_path / "clips").glob("*.mp4"))
    assert len(clips) == 1
    # pre_roll 8 + burst detection (~1-3 s) + post_roll 4, at 1 s segment granularity
    assert 11 <= duration(clips[0]) <= 18, duration(clips[0])
    meta = json.loads(clips[0].with_suffix(".json").read_text())
    assert meta["chat_rate"] > meta["normal_rate"] * 3
    assert any("OMEGALUL" in line for line in meta["chat_sample"])
