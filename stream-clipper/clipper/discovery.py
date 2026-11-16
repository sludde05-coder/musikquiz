"""Finds the biggest live streams for a game across Twitch, YouTube and Kick.

  Twitch  – Helix API, streams in the game's category, sorted by viewers.
  YouTube – Data API search for live videos matching the search terms, then
            concurrent viewer counts. Each search costs 100 of the default
            10,000 daily quota units, hence the slower refresh.
  Kick    – Public API, livestreams in the game's category sorted by viewers.

A platform without credentials is skipped with a warning.
"""
from __future__ import annotations

import logging
import time

import aiohttp

from .config import Config
from .models import Stream, parse_target

log = logging.getLogger(__name__)


class Discovery:
    def __init__(self, cfg: Config, session: aiohttp.ClientSession):
        self.cfg = cfg
        self.s = session
        self._twitch_token: tuple[str, float] | None = None
        self._kick_token: tuple[str, float] | None = None
        self._twitch_game_id: str | None = None
        self._kick_category_id: int | None = cfg.creds.kick_category_id or None
        self._yt_cache: tuple[float, list[Stream]] = (0.0, [])
        self._warned: set[str] = set()

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg)

    async def top_streams(self) -> list[Stream]:
        d = self.cfg.discovery
        found: list[Stream] = []
        for platform, fn in (("twitch", self._twitch), ("youtube", self._youtube), ("kick", self._kick)):
            if platform not in d.platforms:
                continue
            try:
                found += await fn()
            except Exception as e:  # noqa: BLE001
                log.warning("%s discovery failed: %s", platform, e)
        best: dict[str, Stream] = {}
        for st in found:
            if st.viewers >= d.min_viewers and st.viewers > best.get(st.key, Stream("", "", "")).viewers:
                best[st.key] = st
        ranked = sorted(best.values(), key=lambda s: s.viewers, reverse=True)[: d.top_n]
        pinned = [parse_target(t) for t in d.always_track]
        keys = {s.key for s in ranked}
        return ranked + [p for p in pinned if p.key not in keys]

    # ---------- Twitch ----------
    async def _twitch_headers(self) -> dict[str, str] | None:
        c = self.cfg.creds
        if not (c.twitch_client_id and c.twitch_client_secret):
            self._warn_once("twitch", "Twitch credentials missing: skipping Twitch discovery")
            return None
        if not self._twitch_token or self._twitch_token[1] < time.time() + 60:
            async with self.s.post("https://id.twitch.tv/oauth2/token", params={
                "client_id": c.twitch_client_id, "client_secret": c.twitch_client_secret,
                "grant_type": "client_credentials"}) as r:
                r.raise_for_status()
                j = await r.json()
            self._twitch_token = (j["access_token"], time.time() + j["expires_in"])
        return {"Client-Id": c.twitch_client_id, "Authorization": f"Bearer {self._twitch_token[0]}"}

    async def _twitch(self) -> list[Stream]:
        h = await self._twitch_headers()
        if not h:
            return []
        api = "https://api.twitch.tv/helix"
        if not self._twitch_game_id:
            async with self.s.get(f"{api}/games", params={"name": self.cfg.discovery.game}, headers=h) as r:
                r.raise_for_status()
                data = (await r.json())["data"]
            if not data:
                self._warn_once("twitch-game", f"Twitch has no category named {self.cfg.discovery.game!r} yet")
                return []
            self._twitch_game_id = data[0]["id"]
        async with self.s.get(f"{api}/streams", params={"game_id": self._twitch_game_id, "first": 100,
                                                        "type": "live"}, headers=h) as r:
            r.raise_for_status()
            data = (await r.json())["data"]
        return [Stream("twitch", s["user_login"], f"https://www.twitch.tv/{s['user_login']}",
                       s["viewer_count"], s["title"], s["user_name"]) for s in data]

    # ---------- YouTube ----------
    async def _youtube(self) -> list[Stream]:
        key = self.cfg.creds.youtube_api_key
        if not key:
            self._warn_once("youtube", "YouTube API key missing: skipping YouTube discovery")
            return []
        cached_at, cached = self._yt_cache
        if time.time() - cached_at < self.cfg.discovery.youtube_refresh_seconds:
            return cached
        api = "https://www.googleapis.com/youtube/v3"
        q = "|".join(f'"{t}"' for t in self.cfg.discovery.search_terms)
        async with self.s.get(f"{api}/search", params={
            "part": "snippet", "eventType": "live", "type": "video", "q": q,
            "order": "viewCount", "maxResults": 50, "key": key}) as r:
            r.raise_for_status()
            items = (await r.json()).get("items", [])
        ids = [i["id"]["videoId"] for i in items]
        if not ids:
            self._yt_cache = (time.time(), [])
            return []
        async with self.s.get(f"{api}/videos", params={
            "part": "snippet,liveStreamingDetails", "id": ",".join(ids), "key": key}) as r:
            r.raise_for_status()
            videos = (await r.json()).get("items", [])
        terms = [t.lower() for t in self.cfg.discovery.search_terms]
        by_channel: dict[str, Stream] = {}
        for v in videos:
            sn = v["snippet"]
            text = (sn.get("title", "") + " " + sn.get("description", "")).lower()
            if not any(t in text for t in terms):
                continue  # search is fuzzy; keep only streams that actually say GTA 6
            viewers = int(v.get("liveStreamingDetails", {}).get("concurrentViewers", 0))
            st = Stream("youtube", v["id"], f"https://www.youtube.com/watch?v={v['id']}",
                        viewers, sn.get("title", ""), sn.get("channelTitle", ""))
            ch = sn.get("channelId", v["id"])
            if ch not in by_channel or viewers > by_channel[ch].viewers:
                by_channel[ch] = st
        result = list(by_channel.values())
        self._yt_cache = (time.time(), result)
        return result

    # ---------- Kick ----------
    async def _kick_headers(self) -> dict[str, str] | None:
        c = self.cfg.creds
        if not (c.kick_client_id and c.kick_client_secret):
            self._warn_once("kick", "Kick credentials missing: skipping Kick discovery")
            return None
        if not self._kick_token or self._kick_token[1] < time.time() + 60:
            async with self.s.post("https://id.kick.com/oauth/token", data={
                "grant_type": "client_credentials", "client_id": c.kick_client_id,
                "client_secret": c.kick_client_secret}) as r:
                r.raise_for_status()
                j = await r.json()
            self._kick_token = (j["access_token"], time.time() + j.get("expires_in", 3600))
        return {"Authorization": f"Bearer {self._kick_token[0]}", "Accept": "application/json"}

    async def _kick(self) -> list[Stream]:
        h = await self._kick_headers()
        if not h:
            return []
        api = "https://api.kick.com/public/v1"
        if not self._kick_category_id:
            want = {self.cfg.discovery.game.lower(), *(t.lower() for t in self.cfg.discovery.search_terms)}
            async with self.s.get(f"{api}/categories", params={"q": self.cfg.discovery.game}, headers=h) as r:
                r.raise_for_status()
                cats = (await r.json()).get("data", [])
            match = next((c for c in cats if c.get("name", "").lower() in want), None)
            if not match:
                self._warn_once("kick-cat", f"Kick has no category named {self.cfg.discovery.game!r} yet "
                                "(set [kick] category_id to override)")
                return []
            self._kick_category_id = int(match["id"])
        async with self.s.get(f"{api}/livestreams", params={
            "category_id": self._kick_category_id, "sort": "viewer_count", "limit": 100}, headers=h) as r:
            r.raise_for_status()
            data = (await r.json()).get("data", [])
        out = []
        for s in data:
            slug = s.get("slug") or (s.get("channel") or {}).get("slug")
            if slug:
                out.append(Stream("kick", slug.lower(), f"https://kick.com/{slug}",
                                  int(s.get("viewer_count", 0)), s.get("stream_title", ""), slug))
        return out
