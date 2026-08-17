"""WebSocket 实时事件流端点。

客户端连接 /ws/projects/{project_id} 后，实时接收该项目的所有事件。
支持断线重连（通过 after_seq 参数续传）。
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.event_bus import event_bus, Event

logger = logging.getLogger("madp.api.websocket")

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/projects/{project_id}")
async def project_events_ws(websocket: WebSocket, project_id: str):
    """实时事件流 WebSocket。

    客户端消息格式（可选）：
    {"type": "subscribe", "after_seq": 0}  → 订阅（支持续传）
    {"type": "ping"}                       → 心跳
    """
    await websocket.accept()
    logger.info("WebSocket connected: project=%s", project_id)

    # 发送已有事件（初始状态）
    after_seq = 0
    existing = event_bus.get_project_events(project_id, after_seq)
    for event in existing:
        await websocket.send_json(event.to_dict())

    # 订阅新事件
    queue: asyncio.Queue[Event] = asyncio.Queue()

    async def on_event(event: Event) -> None:
        if event.project_id == project_id:
            await queue.put(event)

    event_bus.subscribe(on_event)

    try:
        while True:
            try:
                # 等待新事件或客户端消息
                done, _ = await asyncio.wait(
                    [
                        asyncio.create_task(_recv(websocket)),
                        asyncio.create_task(queue.get()),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    result = task.result()
                    if isinstance(result, Event):
                        await websocket.send_json(result.to_dict())
                    elif isinstance(result, dict):
                        msg_type = result.get("type", "")
                        if msg_type == "ping":
                            await websocket.send_json({"type": "pong"})
                        elif msg_type == "subscribe":
                            after_seq = result.get("after_seq", 0)
                            existing = event_bus.get_project_events(project_id, after_seq)
                            for event in existing:
                                await websocket.send_json(event.to_dict())
            except asyncio.CancelledError:
                break
    except WebSocketDisconnect:
        pass
    finally:
        logger.info("WebSocket disconnected: project=%s", project_id)


async def _recv(websocket: WebSocket) -> dict:
    return await websocket.receive_json()
