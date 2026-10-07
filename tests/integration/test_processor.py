import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Currency, Payment, PaymentStatus
from app.services.exc import (
    PaymentNotFoundError,
    PaymentProcessingError,
    WebhookDeliveryError,
)
from app.services.payment_gateway import PaymentGateway
from app.services.payment_processor import PaymentProcessor
from app.services.webhook import WebhookService

SessionFactory = async_sessionmaker[AsyncSession]
WEBHOOK_URL = "https://merchant.test/webhook"


class SpyGateway(PaymentGateway):
    def __init__(self, failure_rate: float = 0) -> None:
        super().__init__(failure_rate=failure_rate, min_delay_s=0, max_delay_s=0)
        self.calls: list[uuid.UUID] = []

    async def process_payment(self, payment_id: uuid.UUID) -> None:
        self.calls.append(payment_id)
        await super().process_payment(payment_id)


@pytest.fixture
def webhooks() -> list[dict[str, Any]]:
    return []


@pytest.fixture
async def http_client(webhooks: list[dict[str, Any]]) -> AsyncIterator[httpx.AsyncClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        webhooks.append(json.loads(request.content))
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        yield client


def _processor(
    session_factory: SessionFactory, gateway: PaymentGateway, http_client: httpx.AsyncClient
) -> PaymentProcessor:
    return PaymentProcessor(session_factory, gateway, WebhookService(http_client))


async def _create_payment(
    session_factory: SessionFactory, status: PaymentStatus = PaymentStatus.PENDING
) -> uuid.UUID:
    payment = Payment(
        amount=Decimal("10.00"),
        currency=Currency.RUB,
        description="test",
        metadata_={},
        status=status,
        idempotency_key=str(uuid.uuid4()),
        webhook_url=WEBHOOK_URL,
    )
    async with session_factory() as session, session.begin():
        session.add(payment)
    return payment.id


async def _get_payment(session_factory: SessionFactory, payment_id: uuid.UUID) -> Payment:
    async with session_factory() as session:
        payment = await session.get(Payment, payment_id)
    assert payment is not None
    return payment


async def test_pending_payment_is_processed_and_notified(
    session_factory: SessionFactory,
    http_client: httpx.AsyncClient,
    webhooks: list[dict[str, Any]],
) -> None:
    payment_id = await _create_payment(session_factory)
    gateway = SpyGateway()

    await _processor(session_factory, gateway, http_client).process(payment_id)

    payment = await _get_payment(session_factory, payment_id)
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.processed_at is not None
    assert gateway.calls == [payment_id]
    assert webhooks == [{"payment_id": str(payment_id), "status": "succeeded"}]


async def test_failed_processing_leaves_payment_pending(
    session_factory: SessionFactory,
    http_client: httpx.AsyncClient,
    webhooks: list[dict[str, Any]],
) -> None:
    payment_id = await _create_payment(session_factory)

    with pytest.raises(PaymentProcessingError):
        await _processor(session_factory, SpyGateway(failure_rate=1), http_client).process(
            payment_id
        )

    payment = await _get_payment(session_factory, payment_id)
    assert payment.status == PaymentStatus.PENDING
    assert payment.processed_at is None
    assert webhooks == []


@pytest.mark.parametrize("status", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED])
async def test_redelivered_payment_is_not_processed_again(
    session_factory: SessionFactory,
    http_client: httpx.AsyncClient,
    webhooks: list[dict[str, Any]],
    status: PaymentStatus,
) -> None:
    payment_id = await _create_payment(session_factory, status)
    gateway = SpyGateway()

    await _processor(session_factory, gateway, http_client).process(payment_id)

    assert gateway.calls == []
    assert (await _get_payment(session_factory, payment_id)).status == status
    assert webhooks == [{"payment_id": str(payment_id), "status": status.value}]


async def test_failed_webhook_keeps_payment_finalized(
    session_factory: SessionFactory,
    http_client: httpx.AsyncClient,
    webhooks: list[dict[str, Any]],
) -> None:
    payment_id = await _create_payment(session_factory)
    gateway = SpyGateway()
    failing_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))

    with pytest.raises(WebhookDeliveryError):
        await _processor(session_factory, gateway, failing_client).process(payment_id)
    assert (await _get_payment(session_factory, payment_id)).status == PaymentStatus.SUCCEEDED

    # The retry only re-sends the webhook.
    await _processor(session_factory, gateway, http_client).process(payment_id)

    assert gateway.calls == [payment_id]
    assert webhooks == [{"payment_id": str(payment_id), "status": "succeeded"}]


async def test_unknown_payment_raises_not_found(
    session_factory: SessionFactory, http_client: httpx.AsyncClient
) -> None:
    gateway = SpyGateway()

    with pytest.raises(PaymentNotFoundError):
        await _processor(session_factory, gateway, http_client).process(uuid.uuid4())

    assert gateway.calls == []


async def test_fail_marks_payment_failed_and_notifies(
    session_factory: SessionFactory,
    http_client: httpx.AsyncClient,
    webhooks: list[dict[str, Any]],
) -> None:
    payment_id = await _create_payment(session_factory)

    await _processor(session_factory, SpyGateway(), http_client).fail(payment_id)

    payment = await _get_payment(session_factory, payment_id)
    assert payment.status == PaymentStatus.FAILED
    assert payment.processed_at is not None
    assert webhooks == [{"payment_id": str(payment_id), "status": "failed"}]
