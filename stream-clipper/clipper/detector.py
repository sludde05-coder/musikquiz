"""Detects chat "explosions": moments where message rate jumps far above normal.

The detector keeps one bucket per second. Every check compares the rate over
the last few seconds with a robust baseline (median + MAD) of the previous
few minutes. Using median/MAD instead of mean/stddev means earlier spikes
don't inflate the baseline and hide the next one.

Each chatter counts at most once per second, so one person spamming can't
trigger a clip on their own.
"""
from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class DetectorConfig:
    short_window: int = 5          # seconds of chat that make up "right now"
    baseline_window: int = 300     # seconds of history that make up "normal"
    multiplier: float = 3.0        # now must be at least this many times normal
    min_zscore: float = 4.0        # ...and this many spreads above normal
    min_rate: float = 2.0          # ...and at least this many msgs/sec
    warmup: int = 60               # seconds of history needed before firing
    cooldown: int = 90             # seconds between clips on one channel


@dataclass
class Spike:
    detected_at: float   # when the detector fired
    onset: float         # best guess at when chat started exploding
    rate: float          # msgs/sec over the short window
    baseline: float      # normal msgs/sec
    zscore: float

    @property
    def ratio(self) -> float:
        return self.rate / self.baseline if self.baseline > 0 else math.inf


class SpikeDetector:
    def __init__(self, cfg: DetectorConfig | None = None):
        self.cfg = cfg or DetectorConfig()
        self._counts: dict[int, int] = {}
        self._users: dict[int, set[str]] = {}
        self._order: deque[int] = deque()
        self._first_ts: float | None = None
        self._last_spike = -math.inf
        self.last_rate = 0.0
        self.last_baseline = 0.0

    def add(self, user: str, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        if self._first_ts is None:
            self._first_ts = ts
        sec = int(ts)
        users = self._users.get(sec)
        if users is None:
            users = self._users[sec] = set()
            self._counts[sec] = 0
            self._order.append(sec)
        if user in users:
            return
        users.add(user)
        self._counts[sec] += 1

    def _prune(self, now_sec: int) -> None:
        oldest = now_sec - self.cfg.baseline_window - self.cfg.short_window - 5
        while self._order and self._order[0] < oldest:
            sec = self._order.popleft()
            self._counts.pop(sec, None)
            self._users.pop(sec, None)

    def _count(self, sec: int) -> int:
        return self._counts.get(sec, 0)

    def check(self, now: float | None = None) -> Spike | None:
        cfg = self.cfg
        now = time.time() if now is None else now
        now_sec = int(now)
        self._prune(now_sec)
        if self._first_ts is None:
            return None

        # Only complete seconds: the current one is still filling up.
        end = now_sec  # exclusive
        short_start = end - cfg.short_window
        rate = sum(self._count(s) for s in range(short_start, end)) / cfg.short_window

        # Baseline: rates of consecutive short windows before the current one.
        base_start = max(short_start - cfg.baseline_window, int(self._first_ts))
        chunks = []
        s = short_start - cfg.short_window
        while s >= base_start:
            chunks.append(sum(self._count(x) for x in range(s, s + cfg.short_window)) / cfg.short_window)
            s -= cfg.short_window

        self.last_rate = rate
        if not chunks:
            return None
        base = statistics.median(chunks)
        mad = statistics.median(abs(c - base) for c in chunks) * 1.4826
        # Poisson noise floor so a quiet, very regular chat doesn't give spread≈0.
        spread = max(mad, math.sqrt(max(base, 0.1) / cfg.short_window), 0.2)
        z = (rate - base) / spread
        self.last_baseline = base

        if now - self._first_ts < cfg.warmup:
            return None
        if now - self._last_spike < cfg.cooldown:
            return None
        if rate < cfg.min_rate or rate < base * cfg.multiplier or z < cfg.min_zscore:
            return None

        # Walk backwards to find where the surge began (max 30 s back).
        threshold = base + (rate - base) * 0.35
        onset_sec = short_start
        for sec in range(short_start - 1, short_start - 31, -1):
            if self._count(sec) < threshold:
                break
            onset_sec = sec
        # The window that tripped may contain quiet seconds at its start.
        for sec in range(onset_sec, end):
            if self._count(sec) >= threshold:
                onset_sec = sec
                break

        self._last_spike = now
        return Spike(detected_at=now, onset=float(onset_sec), rate=rate, baseline=base, zscore=z)
