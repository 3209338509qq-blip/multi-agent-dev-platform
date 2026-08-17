"""进程内事件总线（asyncio.Queue pub/sub）。

compose 部署时可扩展为 Redis Pub/Sub 实现同一接口。
"""
from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

logger = logging.getLogger("madp.event_bus")


@dataclass
class Event:
    type: str
    project_id: str
    task_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "payload": self.payload,
            "ts": self.ts.isoformat(),
        }


Subscriber = Callable[[Event], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._project_events: dict[str, list[Event]] = {}
        self._persist_fn: Callable[[Event], Awaitable[None]] | None = None
        self._seq: dict[str, int] = {}

    def set_persist_fn(self, fn: Callable[[Event], Awaitable[None]]) -> None:
        self._persist_fn = fn

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    async def emit(self, event: Event) -> None:
        seq = self._seq.get(event.project_id, 0)
        event.payload = event.payload or {}
        event.payload["seq"] = seq
        self._seq[event.project_id] = seq + 1
        self._project_events.setdefault(event.project_id, []).append(event)
        if self._persist_fn:
            try:
                await self._persist_fn(event)
            except Exception:
                logger.exception("event persist failed: %s", event.type)
        for sub in self._subscribers:
            try:
                result = sub(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("subscriber failed for event %s", event.type)

    def get_project_events(self, project_id: str, after_seq: int = 0) -> list[Event]:
        events = self._project_events.get(project_id, [])
        return [e for e in events if (e.payload or {}).get("seq", 0) >= after_seq]


event_bus = EventBus()
