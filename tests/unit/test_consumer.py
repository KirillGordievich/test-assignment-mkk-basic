import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue, TestRabbitBroker

from app.services.exc import (
    PaymentNotFoundError,
    PaymentProcessingError,
    WebhookDeliveryError,
)
from app.worker.consumer import broker
from app.worker.queues import (
    RETRY_COUNT_HEADER,
    payments_exchange,
    payments_queue,
    payments_retry_queues,
)

# The test broker has no dead-lettering, so retry queues get sinks that record what the
# consumer republished. Registered once: subscribers can't be removed from the broker.
retried: dict[str, list[dict[str, Any]]] = {queue.name: [] for queue in payments_retry_queues}


def _register_sink(queue: RabbitQueue) -> None:
    @broker.subscriber(queue, payments_exchange)
    async def sink(body: dict[str, Any], msg: RabbitMessage) -> None:
        retried[queue.name].append({"body": body, "headers": msg.headers})


for _queue in payments_retry_queues:
    _register_sink(_queue)


@pytest.fixture
async def processor() -> AsyncIterator[AsyncMock]:
    for messages in retried.values():
        messages.clear()
    processor = AsyncMock()
    broker.context.set_global("processor", processor)
    yield processor


async def _deliver(test_broker: RabbitBroker, payment_id: uuid.UUID, retry_count: int) -> None:
    await test_broker.publish(
        {"payment_id": str(payment_id)},
        queue=payments_queue,
        exchange=payments_exchange,
        headers={RETRY_COUNT_HEADER: retry_count},
    )


@pytest.mark.parametrize(
    "error",
    [
        PaymentProcessingError("declined"),
        WebhookDeliveryError("webhook is down"),
        OSError("db is down"),
    ],
)
@pytest.mark.parametrize("retry_count", range(len(payments_retry_queues)))
async def test_failed_attempt_goes_to_next_retry_queue(
    processor: AsyncMock, error: Exception, retry_count: int
) -> None:
    processor.process.side_effect = error
    payment_id = uuid.uuid4()

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, payment_id, retry_count)

    retry_queue = payments_retry_queues[retry_count]
    assert retried[retry_queue.name] == [
        {"body": {"payment_id": str(payment_id)}, "headers": {RETRY_COUNT_HEADER: retry_count + 1}}
    ]
    processor.fail.assert_not_awaited()


async def test_exhausted_retries_mark_payment_failed(processor: AsyncMock) -> None:
    processor.process.side_effect = PaymentProcessingError("declined")
    payment_id = uuid.uuid4()

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, payment_id, len(payments_retry_queues))

    processor.fail.assert_awaited_once_with(payment_id)
    assert not any(retried.values())


async def test_exhausted_webhook_retries_keep_payment_status(processor: AsyncMock) -> None:
    processor.process.side_effect = WebhookDeliveryError("webhook is down")

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, uuid.uuid4(), len(payments_retry_queues))

    # The payment is already finalized; only the notification went to the DLQ.
    processor.fail.assert_not_awaited()
    assert not any(retried.values())


async def test_failed_webhook_after_giving_up_still_rejects(processor: AsyncMock) -> None:
    processor.process.side_effect = PaymentProcessingError("declined")
    processor.fail.side_effect = WebhookDeliveryError("webhook is down")
    payment_id = uuid.uuid4()

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, payment_id, len(payments_retry_queues))

    processor.fail.assert_awaited_once_with(payment_id)
    assert not any(retried.values())


async def test_missing_payment_is_not_retried(processor: AsyncMock) -> None:
    processor.process.side_effect = PaymentNotFoundError("missing")

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, uuid.uuid4(), 0)

    processor.fail.assert_not_awaited()
    assert not any(retried.values())


async def test_successful_attempt_is_not_retried(processor: AsyncMock) -> None:
    payment_id = uuid.uuid4()

    async with TestRabbitBroker(broker) as test_broker:
        await _deliver(test_broker, payment_id, 0)

    processor.process.assert_awaited_once_with(payment_id)
    assert not any(retried.values())
