import logging
import uuid
from datetime import timedelta

from app.db import Payment, PaymentStatus
from app.models import PaymentCreate
from app.repositories import OutboxRepository, PaymentRepository
from app.services.exc import IdempotencyKeyConflictError, PaymentNotFoundError

NEW_PAYMENTS_ROUTING_KEY = "payments.new"

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        payment_repo: PaymentRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._payment_repo = payment_repo
        self._outbox_repo = outbox_repo

    async def create(self, idempotency_key: str, data: PaymentCreate) -> Payment:
        """Create a payment together with its outbox event, or return the one already
        created for this idempotency key.
        """
        payment = await self._payment_repo.insert_or_skip(
            idempotency_key,
            amount=data.amount,
            currency=data.currency,
            description=data.description,
            metadata_=data.metadata,
            webhook_url=str(data.webhook_url),
        )
        if payment is None:
            existing = await self._payment_repo.get_by_idempotency_key(idempotency_key)
            if not self._is_same_request(existing, data):
                logger.warning(
                    "Idempotency-Key %r already used for payment %s with a different body",
                    idempotency_key,
                    existing.id,
                )
                raise IdempotencyKeyConflictError
            logger.info(
                "Idempotent replay of payment %s (Idempotency-Key %r)", existing.id, idempotency_key
            )
            return existing

        self._enqueue(payment.id)
        logger.info(
            "Payment %s created: %s %s (Idempotency-Key %r)",
            payment.id,
            payment.amount,
            payment.currency,
            idempotency_key,
        )
        return payment

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._payment_repo.get_by_id(payment_id)

    async def mark_succeeded(self, payment_id: uuid.UUID) -> Payment:
        """Mark payment as SUCCEEDED after successful processing by the gateway."""
        return await self._finalize(payment_id, PaymentStatus.SUCCEEDED)

    async def mark_failed(self, payment_id: uuid.UUID) -> Payment:
        """Mark payment as FAILED after retry exhaustion."""
        return await self._finalize(payment_id, PaymentStatus.FAILED)

    async def get_expired_ids(self, ttl: timedelta, limit: int) -> list[uuid.UUID]:
        """Ids of payments still pending after ``ttl``, e.g. the DB was down when retries
        ran out.
        """
        return await self._payment_repo.get_expired_pending_ids(ttl, limit)

    async def finalize_expired(self, payment_id: uuid.UUID, status: PaymentStatus) -> bool:
        """Move an expired payment to ``status`` and enqueue it again: the consumer finds it
        finalized and only delivers the webhook, with its usual retries. Returns False if the
        payment was finalized meanwhile.
        """
        if await self._payment_repo.set_status(payment_id, status) is None:
            return False
        self._enqueue(payment_id)
        return True

    def _enqueue(self, payment_id: uuid.UUID) -> None:
        self._outbox_repo.create(
            routing_key=NEW_PAYMENTS_ROUTING_KEY,
            payload={"payment_id": str(payment_id)},
        )

    async def _finalize(self, payment_id: uuid.UUID, status: PaymentStatus) -> Payment:
        """Move a pending payment to a final status. A payment finalized by an earlier
        delivery of the same message is returned as is.
        """
        payment = await self._payment_repo.set_status(payment_id, status)
        if payment is None:
            payment = await self._payment_repo.get_by_id(payment_id)
        if payment is None:
            raise PaymentNotFoundError(f"Payment {payment_id} not found")
        return payment

    @staticmethod
    def _is_same_request(payment: Payment, data: PaymentCreate) -> bool:
        return (
            payment.amount == data.amount
            and payment.currency == data.currency
            and payment.description == data.description
            and payment.metadata_ == data.metadata
            and payment.webhook_url == str(data.webhook_url)
        )
