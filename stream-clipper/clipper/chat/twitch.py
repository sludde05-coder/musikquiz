"""Twitch chat via anonymous IRC-over-WebSocket. No login or API key needed."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import AsyncIterator

import aiohttp

from ..models import ChatMessage

log = logging.getLogger(__name__)
IRC_URL = "wss://irc-ws.chat.twitch.tv:443"


def parse_privmsg(line: str) -> ChatMessage | None:
    # Optional tags: "@badge-info=...;display-name=Foo :foo!foo@foo.tmi.twitch.tv PRIVMSG #chan :hello"
    if line.startswith("@"):
        _, _, line = line.partition(" ")
    if " PRIVMSG " not in line or not line.startswith(":"):
        return None
    prefix, _, rest = line[1:].partition(" PRIVMSG ")
    user = prefix.split("!", 1)[0]
    _, _, text = rest.partition(" :")
    return ChatMessage(user=user, text=text, ts=time.time())


async def twitch_chat(channel: str, session: aiohttp.ClientSession) -> AsyncIterator[ChatMessage]:
    backoff = 1
    while True:
        try:
            async with session.ws_connect(IRC_URL, heartbeat=60) as ws:
                await ws.send_str("CAP REQ :twitch.tv/tags")
                await ws.send_str("PASS SCHMOOPIIE")
                await ws.send_str(f"NICK justinfan{random.randint(10000, 99999)}")
                await ws.send_str(f"JOIN #{channel.lower()}")
                log.info("twitch:%s chat connected", channel)
                backoff = 1
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        break
                    for line in msg.data.split("\r\n"):
                        if line.startswith("PING"):
                            await ws.send_str("PONG" + line[4:])
                        elif line.endswith("RECONNECT"):
                            raise ConnectionError("server asked to reconnect")
                        elif (m := parse_privmsg(line)) is not None:
                            yield m
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("twitch:%s chat dropped (%s), retrying in %ss", channel, e, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)
