import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Payment, PaymentStatus
from app.repositories import OutboxRepository, PaymentRepository
from app.services.exc import PaymentNotFoundError
from app.services.payment import PaymentService
from app.services.payment_gateway import PaymentGateway
from app.services.webhook import WebhookPayload, WebhookService

logger = logging.getLogger(__name__)


class PaymentProcessor:
    """Processes a payment through the gateway, moves it to its final status and notifies
    the merchant's webhook.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: PaymentGateway,
        webhooks: WebhookService,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._webhooks = webhooks

    async def process(self, payment_id: uuid.UUID) -> Payment:
        """A redelivered message for an already finalized payment skips the gateway and only
        repeats the webhook: the previous delivery may have died before sending it.
        """
        async with self._payment_service() as service:
            payment = await service.get(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"Payment {payment_id} not found")

        if payment.status == PaymentStatus.PENDING:
            # No transaction is open here: the gateway call takes seconds.
            await self._gateway.process_payment(payment_id)
            async with self._payment_service() as service:
                payment = await service.mark_succeeded(payment_id)
        else:
            logger.info("Payment %s is already %s, skipping processing", payment_id, payment.status)

        await self._notify(payment)
        return payment

    async def fail(self, payment_id: uuid.UUID) -> Payment:
        async with self._payment_service() as service:
            payment = await service.mark_failed(payment_id)
        await self._notify(payment)
        return payment

    @asynccontextmanager
    async def _payment_service(self) -> AsyncIterator[PaymentService]:
        async with self._session_factory() as session, session.begin():
            yield PaymentService(PaymentRepository(session), OutboxRepository(session))

    async def _notify(self, payment: Payment) -> None:
        await self._webhooks.notify(
            payment.webhook_url,
            WebhookPayload(payment_id=str(payment.id), status=payment.status),
        )
