"""One tracked channel: chat reader + spike detector + rolling recorder."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import aiohttp

from .chat import chat_source
from .config import Config
from .detector import Spike, SpikeDetector
from .models import ChatMessage, Stream
from .recorder import Recorder

log = logging.getLogger(__name__)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s)[:60]


class ChannelSession:
    def __init__(self, stream: Stream, cfg: Config, http: aiohttp.ClientSession, *,
                 source_cmd: list[str] | None = None, chat=None):
        self.stream = stream
        self.cfg = cfg
        self.http = http
        self.detector = SpikeDetector(cfg.detector)
        c = cfg.clips
        self.recorder = Recorder(
            stream.key, stream.url, Path(c.buffer_dir) / _safe(stream.key),
            segment_seconds=c.segment_seconds,
            keep_seconds=c.pre_roll + c.chat_delay + c.post_roll + 60,
            quality=c.quality, source_cmd=source_cmd)
        self._chat = chat
        self.recent: deque[ChatMessage] = deque(maxlen=2000)
        self.clips_saved = 0
        self._tasks: list[asyncio.Task] = []
        self._pending: set[asyncio.Task] = set()

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self.recorder.run(), name=f"rec-{self.stream.key}"),
                       asyncio.create_task(self._read_chat(), name=f"chat-{self.stream.key}"),
                       asyncio.create_task(self._watch(), name=f"watch-{self.stream.key}")]

    async def stop(self) -> None:
        # Let clips that are already waiting for their post-roll finish first.
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _read_chat(self) -> None:
        source = self._chat or chat_source(self.stream, self.http, self.cfg.creds)
        async for m in source:
            self.detector.add(m.user, m.ts)
            self.recent.append(m)

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(1)
            spike = self.detector.check()
            if spike and self.recorder.live:
                log.info("🔥 %s chat exploded: %.1f msg/s vs %.1f normal (x%.1f, z=%.1f)",
                         self.stream.key, spike.rate, spike.baseline, spike.ratio, spike.zscore)
                t = asyncio.create_task(self._clip(spike))
                self._pending.add(t)
                t.add_done_callback(self._pending.discard)

    async def _clip(self, spike: Spike) -> None:
        c = self.cfg.clips
        start = spike.onset - c.pre_roll - c.chat_delay
        end = spike.detected_at + c.post_roll - c.chat_delay
        # Wait until the post-roll has been recorded and its segment closed.
        await asyncio.sleep(max(0.0, end - time.time()) + c.segment_seconds * 2 + 1)
        stamp = datetime.fromtimestamp(spike.onset).strftime("%Y%m%d-%H%M%S")
        out = Path(c.output_dir) / f"{_safe(self.stream.key)}_{stamp}.mp4"
        if not await self.recorder.save_clip(start, end, out):
            return
        self.clips_saved += 1
        window = [m for m in self.recent if spike.onset - 5 <= m.ts <= spike.detected_at + 10]
        meta = {
            "platform": self.stream.platform, "channel": self.stream.channel,
            "name": self.stream.display_name or self.stream.channel, "url": self.stream.url,
            "title": self.stream.title, "clip": out.name,
            "explosion_at": datetime.fromtimestamp(spike.onset).isoformat(timespec="seconds"),
            "clip_start": datetime.fromtimestamp(start).isoformat(timespec="seconds"),
            "clip_end": datetime.fromtimestamp(end).isoformat(timespec="seconds"),
            "chat_rate": round(spike.rate, 2), "normal_rate": round(spike.baseline, 2),
            "ratio": round(spike.ratio, 2) if spike.baseline else None, "zscore": round(spike.zscore, 1),
            "chat_sample": [f"{m.user}: {m.text}" for m in window[:40]],
        }
        out.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        with open(Path(c.output_dir) / "index.jsonl", "a") as f:
            f.write(json.dumps({k: v for k, v in meta.items() if k != "chat_sample"}, ensure_ascii=False) + "\n")
        log.info("🎬 saved %s", out)
