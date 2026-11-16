from __future__ import annotations

import asyncio
import logging

import aiohttp

from .config import Config
from .discovery import Discovery
from .models import Stream
from .session import ChannelSession

log = logging.getLogger(__name__)


class Orchestrator:
    """Keeps one ChannelSession per tracked stream and swaps them as rankings change."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sessions: dict[str, ChannelSession] = {}

    async def _sync(self, wanted: list[Stream], http: aiohttp.ClientSession) -> None:
        keys = {s.key for s in wanted}
        for key in [k for k in self.sessions if k not in keys]:
            log.info("⏹  no longer tracking %s", key)
            asyncio.create_task(self.sessions.pop(key).stop())
        for st in wanted:
            if st.key not in self.sessions:
                log.info("▶  tracking %s (%s viewers) %s", st.key, f"{st.viewers:,}", st.title[:60])
                sess = ChannelSession(st, self.cfg, http)
                sess.start()
                self.sessions[st.key] = sess

    def status(self) -> None:
        if not self.sessions:
            log.info("not tracking anything yet")
            return
        lines = [f"{'channel':32} {'video':6} {'chat/s':>7} {'normal':>7} {'clips':>5}"]
        for key, s in self.sessions.items():
            lines.append(f"{key:32} {'live' if s.recorder.live else '--':6} "
                         f"{s.detector.last_rate:7.1f} {s.detector.last_baseline:7.1f} {s.clips_saved:5}")
        log.info("status\n  %s", "\n  ".join(lines))

    async def run_discovery(self) -> None:
        async with aiohttp.ClientSession(trust_env=True) as http:
            disc = Discovery(self.cfg, http)
            status_every, since_status = 30, 0
            while True:
                try:
                    top = await disc.top_streams()
                    log.info("top %d for %r: %s", self.cfg.discovery.top_n, self.cfg.discovery.game,
                             ", ".join(f"{s.key}({s.viewers:,})" for s in top) or "none live")
                    await self._sync(top, http)
                except Exception:  # noqa: BLE001
                    log.exception("discovery round failed")
                waited = 0
                while waited < self.cfg.discovery.refresh_seconds:
                    await asyncio.sleep(5)
                    waited += 5
                    since_status += 5
                    if since_status >= status_every:
                        self.status()
                        since_status = 0

    async def run_fixed(self, streams: list[Stream]) -> None:
        async with aiohttp.ClientSession(trust_env=True) as http:
            await self._sync(streams, http)
            while True:
                await asyncio.sleep(30)
                self.status()
