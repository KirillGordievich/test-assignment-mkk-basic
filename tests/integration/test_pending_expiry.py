import json
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Currency, OutboxEvent, Payment, PaymentStatus
from app.services.payment import NEW_PAYMENTS_ROUTING_KEY
from app.services.payment_gateway import GatewayPaymentStatus, PaymentGateway
from app.services.payment_processor import PaymentProcessor
from app.services.webhook import WebhookService
from app.worker.pending_expiry import PendingPaymentsExpiry

SessionFactory = async_sessionmaker[AsyncSession]
TTL = timedelta(minutes=30)


class StubGateway(PaymentGateway):
    """Answers status lookups from ``statuses``, NOT_FOUND for any other payment."""

    def __init__(self, statuses: dict[uuid.UUID, GatewayPaymentStatus] | None = None) -> None:
        super().__init__(failure_rate=0, min_delay_s=0, max_delay_s=0)
        self._statuses = statuses or {}

    async def get_payment_status(self, payment_id: uuid.UUID) -> GatewayPaymentStatus:
        return self._statuses.get(payment_id, GatewayPaymentStatus.NOT_FOUND)


def _expiry(
    session_factory: SessionFactory,
    gateway: PaymentGateway | None = None,
    batch_size: int = 100,
) -> PendingPaymentsExpiry:
    return PendingPaymentsExpiry(
        session_factory,
        gateway or StubGateway(),
        ttl=TTL,
        batch_size=batch_size,
        interval_s=1,
    )


async def _create_payment(
    session_factory: SessionFactory, status: PaymentStatus, age: timedelta
) -> uuid.UUID:
    payment = Payment(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="test",
        metadata_={},
        status=status,
        idempotency_key=str(uuid.uuid4()),
        webhook_url="https://merchant.test/webhook",
        created_at=func.now() - age,
    )
    async with session_factory() as session, session.begin():
        session.add(payment)
    return payment.id


async def _get_payment(session_factory: SessionFactory, payment_id: uuid.UUID) -> Payment:
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
    assert payment is not None
    return payment


async def _outbox_payment_ids(session_factory: SessionFactory) -> list[str]:
    async with session_factory() as session:
        events = (await session.scalars(select(OutboxEvent))).all()
    assert all(event.routing_key == NEW_PAYMENTS_ROUTING_KEY for event in events)
    return [event.payload["payment_id"] for event in events]


async def test_only_expired_pending_payments_are_failed(session_factory: SessionFactory) -> None:
    expired = await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    fresh = await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(minutes=1))
    succeeded = await _create_payment(session_factory, PaymentStatus.SUCCEEDED, timedelta(hours=10))

    assert await _expiry(session_factory).run_once() == 1

    payment = await _get_payment(session_factory, expired)
    assert payment.status == PaymentStatus.FAILED
    assert payment.processed_at is not None
    assert (await _get_payment(session_factory, fresh)).status == PaymentStatus.PENDING
    assert (await _get_payment(session_factory, succeeded)).status == PaymentStatus.SUCCEEDED
    assert await _outbox_payment_ids(session_factory) == [str(expired)]


async def test_payment_charged_by_gateway_is_marked_succeeded(
    session_factory: SessionFactory,
) -> None:
    payment_id = await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    gateway = StubGateway({payment_id: GatewayPaymentStatus.SUCCEEDED})

    assert await _expiry(session_factory, gateway).run_once() == 1

    assert (await _get_payment(session_factory, payment_id)).status == PaymentStatus.SUCCEEDED
    assert await _outbox_payment_ids(session_factory) == [str(payment_id)]


async def test_payment_in_progress_at_gateway_stays_pending(
    session_factory: SessionFactory,
) -> None:
    payment_id = await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    gateway = StubGateway({payment_id: GatewayPaymentStatus.PENDING})

    assert await _expiry(session_factory, gateway).run_once() == 0

    assert (await _get_payment(session_factory, payment_id)).status == PaymentStatus.PENDING
    assert await _outbox_payment_ids(session_factory) == []


async def test_expired_payment_is_failed_once(session_factory: SessionFactory) -> None:
    await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    expiry = _expiry(session_factory)

    assert await expiry.run_once() == 1
    assert await expiry.run_once() == 0
    assert len(await _outbox_payment_ids(session_factory)) == 1


async def test_expiry_is_batched(session_factory: SessionFactory) -> None:
    for _ in range(3):
        await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    expiry = _expiry(session_factory, batch_size=2)

    assert await expiry.run_once() == 2
    assert await expiry.run_once() == 1
    assert len(set(await _outbox_payment_ids(session_factory))) == 3


async def test_consumer_only_notifies_about_expired_payment(
    session_factory: SessionFactory,
) -> None:
    payment_id = await _create_payment(session_factory, PaymentStatus.PENDING, timedelta(hours=10))
    await _expiry(session_factory).run_once()

    webhooks: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        webhooks.append(json.loads(request.content))
        return httpx.Response(200)

    # failure_rate=1: any gateway call would raise.
    gateway = PaymentGateway(failure_rate=1, min_delay_s=0, max_delay_s=0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        processor = PaymentProcessor(session_factory, gateway, WebhookService(http_client))
        payment = await processor.process(payment_id)

    assert payment.status == PaymentStatus.FAILED
    assert webhooks == [{"payment_id": str(payment_id), "status": "failed"}]
