"""YouTube live chat via the chat-downloader library (no API key needed).

chat-downloader is blocking, so it runs in a thread and hands messages to the
event loop through a queue.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import AsyncIterator

from ..models import ChatMessage

log = logging.getLogger(__name__)


async def youtube_chat(url: str) -> AsyncIterator[ChatMessage]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[ChatMessage] = asyncio.Queue(maxsize=50_000)
    stop = threading.Event()

    def put(m: ChatMessage):
        if not queue.full():
            queue.put_nowait(m)

    def worker():
        from chat_downloader import ChatDownloader
        backoff = 2
        while not stop.is_set():
            try:
                chat = ChatDownloader().get_chat(url, message_groups=["messages", "superchat"])
                log.info("youtube chat connected: %s", url)
                backoff = 2
                for item in chat:
                    if stop.is_set():
                        return
                    user = (item.get("author") or {}).get("name", "?")
                    loop.call_soon_threadsafe(put, ChatMessage(user, item.get("message") or "", time.time()))
            except Exception as e:  # noqa: BLE001
                log.warning("youtube chat dropped for %s (%s), retrying in %ss", url, e, backoff)
            stop.wait(backoff)
            backoff = min(backoff * 2, 120)

    threading.Thread(target=worker, daemon=True, name=f"yt-chat-{url[-11:]}").start()
    try:
        while True:
            yield await queue.get()
    finally:
        stop.set()
