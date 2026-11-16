"""Rolling video buffer.

streamlink pulls the live stream and pipes it into ffmpeg, which cuts it into
short .ts segments named by wall-clock start time. Old segments are deleted,
so disk use stays at a few minutes per channel. When a clip is wanted, the
segments covering that time range are joined into one .mp4 without re-encoding.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
SEG_FMT = "%Y%m%d-%H%M%S"


class Recorder:
    def __init__(self, name: str, url: str, workdir: Path, *, segment_seconds: int = 2,
                 keep_seconds: int = 120, quality: str = "best",
                 source_cmd: list[str] | None = None):
        self.name = name
        self.url = url
        self.dir = workdir
        self.segment_seconds = segment_seconds
        self.keep_seconds = keep_seconds
        self.source_cmd = source_cmd or ["streamlink", "--stdout", "--loglevel", "error",
                                         "--retry-open", "3", url, quality]
        self._procs: list[subprocess.Popen] = []
        self.live = False

    def _start(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        src = subprocess.Popen(self.source_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        ff = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-map", "0:v?", "-map", "0:a?", "-c", "copy",
             "-f", "segment", "-segment_time", str(self.segment_seconds),
             "-reset_timestamps", "1", "-strftime", "1",
             str(self.dir / f"seg_{SEG_FMT}.ts")],
            stdin=src.stdout, stderr=subprocess.DEVNULL)
        src.stdout.close()  # ffmpeg owns the pipe now
        self._procs = [src, ff]

    def _stop(self) -> None:
        for p in self._procs:
            if p.poll() is None:
                p.terminate()
        for p in self._procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        self._procs = []

    async def run(self) -> None:
        backoff = 5
        try:
            while True:
                self._start()
                started = time.time()
                log.info("%s recording started", self.name)
                while all(p.poll() is None for p in self._procs):
                    self.live = True
                    self.prune()
                    await asyncio.sleep(2)
                self.live = False
                self._stop()
                if time.time() - started > 60:
                    backoff = 5
                log.warning("%s recording stopped, restarting in %ss", self.name, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
        finally:
            self.live = False
            self._stop()

    def segments(self) -> list[tuple[float, Path]]:
        out = []
        for p in self.dir.glob("seg_*.ts"):
            try:
                ts = datetime.strptime(p.stem[4:], SEG_FMT).timestamp()
            except ValueError:
                continue
            out.append((ts, p))
        out.sort()
        return out

    def prune(self) -> None:
        cutoff = time.time() - self.keep_seconds
        for ts, p in self.segments():
            if ts < cutoff:
                p.unlink(missing_ok=True)

    async def save_clip(self, start: float, end: float, out: Path) -> bool:
        segs = self.segments()[:-1]  # newest one is still being written
        chosen = [p for ts, p in segs if ts + self.segment_seconds > start and ts < end]
        if not chosen:
            log.error("%s no buffered video for %s..%s", self.name, start, end)
            return False
        out.parent.mkdir(parents=True, exist_ok=True)
        # Copy first so pruning can't delete a segment mid-concat.
        tmp = out.with_suffix(".parts")
        tmp.mkdir(exist_ok=True)
        listing = tmp / "list.txt"
        lines = []
        for i, p in enumerate(chosen):
            dst = tmp / f"{i:04d}.ts"
            try:
                shutil.copyfile(p, dst)
            except FileNotFoundError:
                continue
            lines.append(f"file '{dst.name}'")
        listing.write_text("\n".join(lines))
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(out),
            stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate()
        shutil.rmtree(tmp, ignore_errors=True)
        if proc.returncode != 0:
            log.error("%s ffmpeg concat failed: %s", self.name, err.decode(errors="replace")[-500:])
            return False
        return True
