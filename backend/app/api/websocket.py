"""项目事件流。after_seq 指定要接收的最小事件序号。"""
from __future__ import annotations

import asyncio
import logging

from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import database
from app.services.event_bus import EVENT_PAGE_SIZE, Event, event_bus, read_project_events

logger = logging.getLogger("madp.api.websocket")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/projects/{project_id}")
async def project_events_ws(websocket: WebSocket, project_id: str, after_seq: int = 0):
    await websocket.accept()
    events_available = asyncio.Event()
    events_available.set()

    def on_event(event: Event) -> None:
        if event.project_id == project_id:
            events_available.set()

    # 先订阅再读取历史。回放期间收到的通知会触发下一次查询。
    event_bus.subscribe(on_event)
    receive = asyncio.create_task(websocket.receive_json())
    wake = asyncio.create_task(events_available.wait())
    try:
        while True:
            done, _ = await asyncio.wait([receive, wake], return_when=asyncio.FIRST_COMPLETED)
            if receive in done:
                message = receive.result()
                if isinstance(message, dict):
                    if message.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif message.get("type") == "subscribe":
                        requested = message.get("after_seq", 0)
                        if type(requested) is int and requested >= 0:
                            after_seq = requested
                            events_available.set()
                receive = asyncio.create_task(websocket.receive_json())

            if wake in done:
                events_available.clear()
                async with database.async_session_factory() as db:
                    events = await read_project_events(db, project_id, after_seq)
                for event in events:
                    await websocket.send_json(event.to_dict())
                    after_seq = event.seq + 1
                if len(events) == EVENT_PAGE_SIZE:
                    events_available.set()
                wake = asyncio.create_task(events_available.wait())
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        event_bus.unsubscribe(on_event)
        receive.cancel()
        wake.cancel()
        with CancelScope(shield=True):
            await asyncio.gather(receive, wake, return_exceptions=True)
        logger.debug("WebSocket disconnected: project=%s", project_id)
