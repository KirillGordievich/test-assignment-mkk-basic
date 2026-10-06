import uuid

from app.db import Payment
from app.models import PaymentCreate
from app.repositories import OutboxRepository, PaymentRepository
from app.services.exc import IdempotencyKeyConflictError

NEW_PAYMENTS_ROUTING_KEY = "payments.new"


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
                raise IdempotencyKeyConflictError
            return existing

        self._outbox_repo.create(
            routing_key=NEW_PAYMENTS_ROUTING_KEY,
            payload={"payment_id": str(payment.id)},
        )
        return payment

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._payment_repo.get_by_id(payment_id)

    @staticmethod
    def _is_same_request(payment: Payment, data: PaymentCreate) -> bool:
        return (
            payment.amount == data.amount
            and payment.currency == data.currency
            and payment.description == data.description
            and payment.metadata_ == data.metadata
            and payment.webhook_url == str(data.webhook_url)
        )
