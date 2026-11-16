"""
python -m clipper run                      # auto-track the top 10 GTA 6 streams
python -m clipper discover                 # just print the current top 10
python -m clipper watch twitch:xqc kick:adinross youtube:VIDEO_ID
python -m clipper simulate                 # see the spike detector on fake chat
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random

import aiohttp

from .config import load_config


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipper", description="Clip livestreams when chat explodes.")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="track the top N streams of the configured game")
    r.add_argument("--game", help="override the game (e.g. to test on a game that's live now)")
    d = sub.add_parser("discover", help="print the current top streams and exit")
    d.add_argument("--game")
    w = sub.add_parser("watch", help="track specific channels")
    w.add_argument("targets", nargs="+", help="twitch:login, kick:slug, youtube:VIDEO_ID or URLs")
    sub.add_parser("simulate", help="run the detector on synthetic chat")
    a = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("chat_downloader", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config(a.config)
    if getattr(a, "game", None):
        cfg.discovery.game = a.game
        cfg.discovery.search_terms = [a.game]

    from .orchestrator import Orchestrator
    from .models import parse_target
    try:
        if a.cmd == "run":
            asyncio.run(Orchestrator(cfg).run_discovery())
        elif a.cmd == "watch":
            asyncio.run(Orchestrator(cfg).run_fixed([parse_target(t) for t in a.targets]))
        elif a.cmd == "discover":
            asyncio.run(_discover(cfg))
        elif a.cmd == "simulate":
            _simulate(cfg)
    except KeyboardInterrupt:
        pass


async def _discover(cfg) -> None:
    from .discovery import Discovery
    async with aiohttp.ClientSession(trust_env=True) as http:
        top = await Discovery(cfg, http).top_streams()
    if not top:
        print("Nothing live (or no credentials configured).")
    for i, s in enumerate(top, 1):
        print(f"{i:2}. {s.platform:8} {s.display_name or s.channel:24} {s.viewers:>9,}  {s.title[:60]}")


def _simulate(cfg) -> None:
    from .detector import SpikeDetector
    det = SpikeDetector(cfg.detector)
    rng = random.Random(7)
    explosions = {240: 12, 420: 6, 600: 20}  # second -> how many times normal
    t0, normal = 1_000_000.0, 8
    print(f"Simulating 12 min of chat at ~{normal} msg/s with explosions at "
          f"{', '.join(f'{s}s (x{m})' for s, m in explosions.items())}\n")
    for sec in range(720):
        mult = 1
        for s, m in explosions.items():
            if s <= sec < s + 15:
                mult = m
        for _ in range(_poisson(rng, normal * mult)):
            det.add(f"user{rng.randint(0, 20000)}", t0 + sec + rng.random())
        spike = det.check(t0 + sec + 1)
        if spike:
            print(f"  🔥 fired at {spike.detected_at - t0:5.0f}s  onset {spike.onset - t0:5.0f}s  "
                  f"{spike.rate:6.1f} msg/s vs {spike.baseline:4.1f} normal  →  clip "
                  f"{spike.onset - t0 - cfg.clips.pre_roll:.0f}s..{spike.detected_at - t0 + cfg.clips.post_roll:.0f}s")


def _poisson(rng: random.Random, lam: float) -> int:
    # Knuth for small λ, normal approximation for large.
    if lam > 50:
        return max(0, int(rng.gauss(lam, lam ** 0.5)))
    import math
    L, k, p = math.exp(-lam), 0, 1.0
    while p > L:
        k += 1
        p *= rng.random()
    return k - 1


if __name__ == "__main__":
    main()
