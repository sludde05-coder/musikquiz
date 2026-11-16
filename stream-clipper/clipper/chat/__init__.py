from __future__ import annotations

from typing import AsyncIterator

import aiohttp

from ..config import Credentials
from ..models import ChatMessage, Stream


def chat_source(stream: Stream, session: aiohttp.ClientSession, creds: Credentials) -> AsyncIterator[ChatMessage]:
    if stream.platform == "twitch":
        from .twitch import twitch_chat
        return twitch_chat(stream.channel, session)
    if stream.platform == "kick":
        from .kick import kick_chat
        return kick_chat(stream.channel, session, creds)
    if stream.platform == "youtube":
        from .youtube import youtube_chat
        return youtube_chat(stream.url)
    raise ValueError(stream.platform)
