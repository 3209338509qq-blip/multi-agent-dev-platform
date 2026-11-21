"""进程内事件发布与数据库事件读写。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event as StoredEvent

logger = logging.getLogger("madp.event_bus")
EVENT_PAGE_SIZE = 500


@dataclass
class Event:
    type: str
    project_id: str
    task_id: str | None = None
    run_id: str | None = None
    payload: dict[str, Any] | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        timestamp = self.ts if self.ts.tzinfo else self.ts.replace(tzinfo=timezone.utc)
        return {
            "type": self.type,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "payload": {**(self.payload or {}), "seq": self.seq},
            "ts": timestamp.isoformat(),
            "seq": self.seq,
        }


async def store_project_event(db: AsyncSession, event: Event) -> int:
    row = StoredEvent(
        project_id=event.project_id,
        task_id=event.task_id,
        run_id=event.run_id,
        type=event.type,
        payload=event.payload,
        ts=event.ts,
    )
    db.add(row)
    await db.flush()
    row.seq = row.id
    return row.id


async def read_project_events(db: AsyncSession, project_id: str, after_seq: int = 0) -> list[Event]:
    """用持久化主键作为游标，旧记录也能按同一规则续传。"""
    result = await db.scalars(
        select(StoredEvent).where(
            StoredEvent.project_id == project_id,
            StoredEvent.id >= after_seq,
        ).order_by(StoredEvent.id).limit(EVENT_PAGE_SIZE)
    )
    return [
        Event(
            type=row.type, project_id=row.project_id, task_id=row.task_id, run_id=row.run_id,
            payload=row.payload, ts=row.ts, seq=row.id,
        )
        for row in result
    ]


Subscriber = Callable[[Event], Awaitable[None] | None]
PersistEvent = Callable[[Event], Awaitable[int]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._project_events: dict[str, list[Event]] = {}
        self._persist_fn: PersistEvent | None = None
        self._persist_lock = asyncio.Lock()

    def set_persist_fn(self, fn: PersistEvent | None) -> None:
        self._persist_fn = fn
        self._persist_lock = asyncio.Lock()

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def unsubscribe(self, fn: Subscriber) -> None:
        self._subscribers.remove(fn)

    async def emit(self, event: Event) -> None:
        if self._persist_fn is not None:
            try:
                # 同一进程按提交顺序公布游标，避免回放跳过尚未提交的事件。
                async with self._persist_lock:
                    event.seq = await self._persist_fn(event)
            except Exception:
                logger.exception("event persist failed: %s", event.type)
                return
        else:
            events = self._project_events.setdefault(event.project_id, [])
            event.seq = len(events) + 1
            events.append(event)

        event.payload = {**(event.payload or {}), "seq": event.seq}
        for sub in tuple(self._subscribers):
            try:
                result = sub(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("subscriber failed for event %s", event.type)

    def get_project_events(self, project_id: str, after_seq: int = 0) -> list[Event]:
        events = self._project_events.get(project_id, [])
        return [event for event in events if event.seq >= after_seq]


event_bus = EventBus()
