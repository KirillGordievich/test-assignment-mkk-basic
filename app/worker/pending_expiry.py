import asyncio
import contextlib
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db import PaymentStatus
from app.db.engine import engine, session_factory
from app.logging import setup_logging
from app.repositories import OutboxRepository, PaymentRepository
from app.services.payment import PaymentService
from app.services.payment_gateway import GatewayPaymentStatus, PaymentGateway

logger = logging.getLogger(__name__)


class PendingPaymentsExpiry:
    """Periodically finalizes payments stuck in pending for longer than the TTL, according
    to what the gateway knows about them.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        gateway: PaymentGateway,
        ttl: timedelta,
        batch_size: int,
        interval_s: float,
    ) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._ttl = ttl
        self._batch_size = batch_size
        self._interval_s = interval_s

    async def run_once(self) -> int:
        """Finalize one batch of expired payments and return how many were finalized."""
        async with self._payment_service() as service:
            payment_ids = await service.get_expired_ids(self._ttl, self._batch_size)

        finalized = 0
        for payment_id in payment_ids:
            # No transaction is open here: the gateway is an external call.
            gateway_status = await self._gateway.get_payment_status(payment_id)
            if gateway_status == GatewayPaymentStatus.PENDING:
                logger.info("Expired payment %s is still in progress at the gateway", payment_id)
                continue
            # Charged by the gateway, but the result never reached the DB.
            if gateway_status == GatewayPaymentStatus.SUCCEEDED:
                status = PaymentStatus.SUCCEEDED
            else:
                status = PaymentStatus.FAILED

            async with self._payment_service() as service:
                if not await service.finalize_expired(payment_id, status):
                    continue
            finalized += 1
            logger.warning(
                "Payment %s pending for over %s, gateway says %s: marked %s",
                payment_id,
                self._ttl,
                gateway_status,
                status,
            )
        return finalized

    @asynccontextmanager
    async def _payment_service(self) -> AsyncIterator[PaymentService]:
        async with self._session_factory() as session, session.begin():
            yield PaymentService(PaymentRepository(session), OutboxRepository(session))

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "Pending payments expiry started (interval=%.0fs, ttl=%s, batch_size=%d)",
            self._interval_s,
            self._ttl,
            self._batch_size,
        )
        while not stop.is_set():
            try:
                finalized = await self.run_once()
            except Exception:
                logger.exception("Pending payments expiry iteration failed")
                finalized = 0

            # A fully finalized batch means there are probably more expired payments, so don't
            # wait. Payments the gateway still processes make it partial and wait for next tick.
            if finalized < self._batch_size:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._interval_s)


async def main() -> None:
    setup_logging()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    gateway = PaymentGateway(
        failure_rate=settings.gateway.failure_rate,
        min_delay_s=settings.gateway.min_delay_s,
        max_delay_s=settings.gateway.max_delay_s,
    )
    expiry = PendingPaymentsExpiry(
        session_factory,
        gateway,
        ttl=timedelta(seconds=settings.expiry.ttl_s),
        batch_size=settings.expiry.batch_size,
        interval_s=settings.expiry.interval_s,
    )
    try:
        await expiry.run(stop)
    finally:
        await engine.dispose()
    logger.info("Pending payments expiry stopped")


if __name__ == "__main__":
    asyncio.run(main())
