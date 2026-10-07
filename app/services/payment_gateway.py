import asyncio
import logging
import random
import uuid

from app.services.exc import PaymentProcessingError

logger = logging.getLogger(__name__)


class PaymentGateway:
    """Emulates an external payment gateway: random latency and a share of failed payments."""

    def __init__(self, failure_rate: float, min_delay_s: float, max_delay_s: float) -> None:
        self._failure_rate = failure_rate
        self._min_delay_s = min_delay_s
        self._max_delay_s = max_delay_s
        self._processed_ids: set[uuid.UUID] = set()

    async def process_payment(self, payment_id: uuid.UUID) -> None:
        if payment_id in self._processed_ids:
            logger.info(
                "Gateway: payment %s is already processed, returning its result", payment_id
            )
            return

        await asyncio.sleep(random.uniform(self._min_delay_s, self._max_delay_s))

        if random.random() < self._failure_rate:
            raise PaymentProcessingError(f"Processing failed for {payment_id}")

        self._processed_ids.add(payment_id)
