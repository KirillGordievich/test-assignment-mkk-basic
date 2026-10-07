import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from faststream import Context, ContextRepo, FastStream
from faststream.exceptions import RejectMessage
from faststream.rabbit import RabbitMessage
from pydantic import BaseModel

from app.config import settings
from app.db.engine import engine, session_factory
from app.logging import setup_logging
from app.services.exc import (
    PaymentNotFoundError,
    PaymentProcessingError,
    WebhookDeliveryError,
)
from app.services.payment_gateway import PaymentGateway
from app.services.payment_processor import PaymentProcessor
from app.services.webhook import WebhookService
from app.worker.broker import broker
from app.worker.queues import (
    RETRY_COUNT_HEADER,
    declare_payments_queues,
    payments_exchange,
    payments_queue,
    payments_retry_queues,
)

setup_logging()
logger = logging.getLogger(__name__)


class PaymentMessage(BaseModel):
    payment_id: uuid.UUID


@asynccontextmanager
async def lifespan(context: ContextRepo) -> AsyncIterator[None]:
    gateway = PaymentGateway(
        failure_rate=settings.gateway.failure_rate,
        min_delay_s=settings.gateway.min_delay_s,
        max_delay_s=settings.gateway.max_delay_s,
    )
    async with httpx.AsyncClient() as http_client:
        context.set_global(
            "processor", PaymentProcessor(session_factory, gateway, WebhookService(http_client))
        )
        yield
    await engine.dispose()


app = FastStream(broker, lifespan=lifespan)


@app.on_startup
async def declare_queues() -> None:
    # Declare before consuming starts, so a failed message always has a retry queue.
    await broker.connect()
    await declare_payments_queues(broker)


@broker.subscriber(payments_queue, payments_exchange)
async def process_payment(
    body: PaymentMessage,
    msg: RabbitMessage,
    processor: Annotated[PaymentProcessor, Context()],
) -> None:
    """Any error but a missing payment is retried with exponential backoff. A redelivered
    message for an already finalized payment only re-sends the webhook, so a failed webhook
    is retried the same way. Once retries are exhausted, the message goes to the DLQ and
    a still pending payment is marked FAILED.
    """
    retry_count = int(msg.headers.get(RETRY_COUNT_HEADER, 0))
    attempt = f"{retry_count + 1}/{settings.consumer.max_retries}"
    logger.info("Processing payment %s (attempt %s)", body.payment_id, attempt)

    try:
        payment = await processor.process(body.payment_id)
    except PaymentNotFoundError:
        # Retrying won't make the payment appear.
        logger.error("Payment %s not found, sending to DLQ", body.payment_id)
        raise RejectMessage from None
    except Exception as error:
        # Declines and webhook failures are expected; anything else (DB, broker) deserves
        # a traceback.
        exc_info = not isinstance(error, PaymentProcessingError | WebhookDeliveryError)

        if retry_count >= len(payments_retry_queues):
            logger.error(
                "Payment %s: attempt %s failed (%s), retries exhausted, sending to DLQ",
                body.payment_id,
                attempt,
                error,
                exc_info=exc_info,
            )
            # A webhook error means the payment is already finalized: only the notification
            # is lost, and replaying the message from the DLQ re-sends it.
            if not isinstance(error, WebhookDeliveryError):
                await _give_up(processor, body.payment_id)
            raise RejectMessage from None

        retry_queue = payments_retry_queues[retry_count]
        logger.warning(
            "Payment %s: attempt %s failed (%s), retrying via %s",
            body.payment_id,
            attempt,
            error,
            retry_queue.name,
            exc_info=exc_info,
        )
        await broker.publish(
            body,
            exchange=payments_exchange,
            routing_key=retry_queue.routing_key,
            headers={RETRY_COUNT_HEADER: retry_count + 1},
            persist=True,
        )
        return

    logger.info("Payment %s processed: %s", body.payment_id, payment.status)


async def _give_up(processor: PaymentProcessor, payment_id: uuid.UUID) -> None:
    """Mark the payment FAILED. If the DB is still down, the error rejects the message to
    the DLQ anyway and the payment stays pending until pending expiry fails it.
    """
    try:
        payment = await processor.fail(payment_id)
    except WebhookDeliveryError as error:
        logger.warning("Payment %s marked failed, but %s", payment_id, error)
        return
    logger.info("Payment %s finalized after retries exhausted: %s", payment_id, payment.status)
