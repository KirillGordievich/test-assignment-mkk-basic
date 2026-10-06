from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import session_factory
from app.repositories import OutboxRepository, PaymentRepository
from app.services.payment import PaymentService


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        async with session.begin():
            yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_payment_repo(session: SessionDep) -> PaymentRepository:
    return PaymentRepository(session)


async def get_outbox_repo(session: SessionDep) -> OutboxRepository:
    return OutboxRepository(session)


PaymentRepoDep = Annotated[PaymentRepository, Depends(get_payment_repo)]
OutboxRepoDep = Annotated[OutboxRepository, Depends(get_outbox_repo)]


async def get_payment_service(
    payment_repo: PaymentRepoDep,
    outbox_repo: OutboxRepoDep,
) -> PaymentService:
    return PaymentService(payment_repo, outbox_repo)


PaymentServiceDep = Annotated[PaymentService, Depends(get_payment_service)]
