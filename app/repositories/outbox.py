from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import OutboxEvent


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def create(self, routing_key: str, payload: dict[str, Any]) -> None:
        self._session.add(OutboxEvent(routing_key=routing_key, payload=payload))
