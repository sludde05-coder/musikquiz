"""Kick chat via Kick's Pusher WebSocket.

Needs the channel's chatroom id, which comes from kick.com/api/v2/channels/<slug>.
That endpoint sits behind Cloudflare and sometimes refuses scripts; if it does,
put the id in config as  always_track = ["kick:slug#123456"].
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

import aiohttp

from ..config import Credentials
from ..models import ChatMessage

log = logging.getLogger(__name__)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


async def chatroom_id(slug: str, session: aiohttp.ClientSession) -> int:
    async with session.get(f"https://kick.com/api/v2/channels/{slug}",
                           headers={"User-Agent": UA, "Accept": "application/json"}) as r:
        r.raise_for_status()
        data = await r.json(content_type=None)
    return int(data["chatroom"]["id"])


async def kick_chat(channel: str, session: aiohttp.ClientSession, creds: Credentials) -> AsyncIterator[ChatMessage]:
    slug, _, room = channel.partition("#")
    backoff = 2
    while True:
        try:
            room_id = int(room) if room else await chatroom_id(slug, session)
            url = (f"wss://ws-{creds.kick_pusher_cluster}.pusher.com/app/{creds.kick_pusher_key}"
                   "?protocol=7&client=js&version=8.4.0&flash=false")
            async with session.ws_connect(url, heartbeat=60) as ws:
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    ev = json.loads(msg.data)
                    name = ev.get("event", "")
                    if name == "pusher:connection_established":
                        await ws.send_str(json.dumps({"event": "pusher:subscribe",
                                                      "data": {"auth": "", "channel": f"chatrooms.{room_id}.v2"}}))
                        log.info("kick:%s chat connected (room %s)", slug, room_id)
                        backoff = 2
                    elif name == "pusher:ping":
                        await ws.send_str(json.dumps({"event": "pusher:pong", "data": {}}))
                    elif name.endswith("ChatMessageEvent"):
                        data = json.loads(ev["data"]) if isinstance(ev.get("data"), str) else ev.get("data", {})
                        user = (data.get("sender") or {}).get("username", "?")
                        yield ChatMessage(user=user, text=data.get("content", ""), ts=time.time())
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("kick:%s chat dropped (%s), retrying in %ss", slug, e, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 120)
