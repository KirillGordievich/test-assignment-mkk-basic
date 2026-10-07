import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import OutboxEvent


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(self, routing_key: str, payload: dict[str, Any]) -> None:
        self._session.add(OutboxEvent(routing_key=routing_key, payload=payload))

    async def fetch_unpublished(self, limit: int) -> list[OutboxEvent]:
        result = await self._session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def mark_published(self, event_ids: Sequence[uuid.UUID]) -> None:
        await self._session.execute(
            update(OutboxEvent).where(OutboxEvent.id.in_(event_ids)).values(published_at=func.now())
        )
