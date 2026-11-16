from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass(frozen=True)
class Stream:
    platform: str        # "twitch" | "youtube" | "kick"
    channel: str         # login / slug / YouTube video id
    url: str
    viewers: int = 0
    title: str = ""
    display_name: str = ""

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.channel}"


@dataclass
class ChatMessage:
    user: str
    text: str
    ts: float = field(default_factory=time.time)


def parse_target(spec: str) -> Stream:
    """Turn 'twitch:xqc', 'kick:adinross', 'youtube:VIDEOID' or a URL into a Stream."""
    s = spec.strip()
    low = s.lower()
    if low.startswith("http"):
        if "twitch.tv/" in low:
            return parse_target("twitch:" + s.rstrip("/").rsplit("/", 1)[-1])
        if "kick.com/" in low:
            return parse_target("kick:" + s.rstrip("/").rsplit("/", 1)[-1])
        if "youtube.com" in low or "youtu.be" in low:
            vid = _youtube_id(s)
            return Stream("youtube", vid or s, s if not vid else f"https://www.youtube.com/watch?v={vid}")
        raise ValueError(f"Unsupported URL: {spec}")
    if ":" not in s:
        raise ValueError(f"Use platform:channel, got {spec!r}")
    platform, channel = s.split(":", 1)
    platform = platform.lower()
    if platform == "twitch":
        channel = channel.lower()
        return Stream("twitch", channel, f"https://www.twitch.tv/{channel}")
    if platform == "kick":
        channel = channel.lower()  # may carry a chatroom id: "slug#123456"
        return Stream("kick", channel, f"https://kick.com/{channel.split('#')[0]}")
    if platform in ("youtube", "yt"):
        return Stream("youtube", channel, f"https://www.youtube.com/watch?v={channel}")
    raise ValueError(f"Unknown platform {platform!r} (use twitch, youtube or kick)")


def _youtube_id(url: str) -> str | None:
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url)
    if u.netloc.endswith("youtu.be"):
        return u.path.strip("/") or None
    if "v" in parse_qs(u.query):
        return parse_qs(u.query)["v"][0]
    parts = u.path.strip("/").split("/")
    if len(parts) == 2 and parts[0] == "live":
        return parts[1]
    return None
