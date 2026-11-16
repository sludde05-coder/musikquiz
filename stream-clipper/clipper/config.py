from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .detector import DetectorConfig


@dataclass
class DiscoveryConfig:
    game: str = "Grand Theft Auto VI"
    search_terms: list[str] = field(default_factory=lambda: ["GTA 6", "GTA VI", "Grand Theft Auto VI"])
    top_n: int = 10
    min_viewers: int = 500
    platforms: list[str] = field(default_factory=lambda: ["twitch", "youtube", "kick"])
    refresh_seconds: int = 300
    youtube_refresh_seconds: int = 900   # YouTube search costs 100 quota units
    always_track: list[str] = field(default_factory=list)


@dataclass
class ClipConfig:
    output_dir: str = "clips"
    buffer_dir: str = "buffer"
    pre_roll: int = 30        # seconds kept before the chat explosion
    post_roll: int = 20       # seconds kept after the detector fires
    chat_delay: int = 0       # extra seconds to shift the clip earlier
    segment_seconds: int = 2
    quality: str = "best"


@dataclass
class VerticalConfig:
    enabled: bool = True           # also render a 9:16 captioned version of each clip
    layout: str = "blur"           # "blur" (full frame over blurred fill) or "crop"
    speech_captions: bool = True   # word-by-word captions from Whisper
    whisper_model: str = "small"   # tiny / base / small / medium / large-v3
    ai_captions: bool = True       # let Claude write the hook and reaction captions
    ai_model: str = "claude-opus-5-5"
    font: str = "Arial"
    crf: int = 21                  # quality: lower = better and bigger
    preset: str = "veryfast"
    max_parallel: int = 1          # renders at once (CPU heavy)


@dataclass
class Credentials:
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    youtube_api_key: str = ""
    kick_client_id: str = ""
    kick_client_secret: str = ""
    kick_category_id: int = 0
    kick_pusher_key: str = "32cbd69e4b950bf97679"
    kick_pusher_cluster: str = "us2"


@dataclass
class Config:
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    clips: ClipConfig = field(default_factory=ClipConfig)
    vertical: VerticalConfig = field(default_factory=VerticalConfig)
    creds: Credentials = field(default_factory=Credentials)


def _fill(obj, data: dict, prefix: str = ""):
    names = {f.name for f in fields(obj)}
    for k, v in data.items():
        name = prefix + k
        if name in names:
            setattr(obj, name, v)


def load_config(path: str | None) -> Config:
    cfg = Config()
    if path and Path(path).exists():
        data = tomllib.loads(Path(path).read_text())
        _fill(cfg.discovery, data.get("discovery", {}))
        _fill(cfg.detector, data.get("detector", {}))
        _fill(cfg.clips, data.get("clips", {}))
        _fill(cfg.vertical, data.get("vertical", {}))
        for platform in ("twitch", "youtube", "kick"):
            _fill(cfg.creds, data.get(platform, {}), prefix=platform + "_")
    # Environment variables win, so secrets can stay out of the file.
    for f in fields(cfg.creds):
        env = os.environ.get(f.name.upper())
        if env:
            setattr(cfg.creds, f.name, type(getattr(cfg.creds, f.name))(env))
    return cfg
