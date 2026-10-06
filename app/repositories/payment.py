import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Payment, PaymentStatus


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_or_skip(
        self,
        idempotency_key: str,
        *,
        amount: Any,
        currency: Any,
        description: str,
        metadata_: dict[str, Any],
        webhook_url: str,
    ) -> Payment | None:
        return await self._session.scalar(
            insert(Payment)
            .values(
                idempotency_key=idempotency_key,
                amount=amount,
                currency=currency,
                description=description,
                metadata_=metadata_,
                webhook_url=webhook_url,
                status=PaymentStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
            .returning(Payment)
        )

    async def get_by_idempotency_key(self, key: str) -> Payment:
        result = await self._session.execute(
            select(Payment).where(Payment.idempotency_key == key)
        )
        return result.scalar_one()

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id)
