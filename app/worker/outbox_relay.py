import asyncio
import contextlib
import logging

from faststream import FastStream
from faststream.rabbit import RabbitBroker, RabbitExchange
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.db.engine import engine, session_factory
from app.logging import setup_logging
from app.repositories import OutboxRepository
from app.worker.broker import broker
from app.worker.queues import declare_payments_queues, payments_exchange

setup_logging()
logger = logging.getLogger(__name__)


class OutboxRelay:
    """Polls the outbox for unpublished events and publishes them to RabbitMQ."""

    def __init__(
        self,
        broker: RabbitBroker,
        session_factory: async_sessionmaker[AsyncSession],
        exchange: RabbitExchange,
        batch_size: int,
        poll_interval_s: float,
    ) -> None:
        self._broker = broker
        self._session_factory = session_factory
        self._exchange = exchange
        self._batch_size = batch_size
        self._poll_interval_s = poll_interval_s

    async def run_once(self) -> int:
        """Publish one batch of events and return how many were published."""
        async with self._session_factory() as session, session.begin():
            repo = OutboxRepository(session)
            events = await repo.fetch_unpublished(self._batch_size)
            for event in events:
                await self._broker.publish(
                    event.payload,
                    exchange=self._exchange,
                    routing_key=event.routing_key,
                    persist=True,
                )
            if events:
                await repo.mark_published([event.id for event in events])
        if events:
            logger.info(
                "Published %d outbox events: %s",
                len(events),
                ", ".join(str(event.payload.get("payment_id", event.id)) for event in events),
            )
        return len(events)

    async def run(self, stop: asyncio.Event) -> None:
        logger.info(
            "Outbox relay started (poll_interval=%.1fs, batch_size=%d)",
            self._poll_interval_s,
            self._batch_size,
        )
        while not stop.is_set():
            try:
                published = await self.run_once()
            except Exception:
                logger.exception("Outbox relay iteration failed")
                published = 0

            # A full batch means there is probably more to publish, so don't wait.
            if published < self._batch_size:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), self._poll_interval_s)


relay = OutboxRelay(
    broker,
    session_factory,
    payments_exchange,
    batch_size=settings.outbox.batch_size,
    poll_interval_s=settings.outbox.poll_interval_s,
)
stop = asyncio.Event()
app = FastStream(broker)


@app.after_startup
async def start_relay() -> None:
    await declare_payments_queues(broker)
    app.context.set_global("relay_task", asyncio.create_task(relay.run(stop)))


@app.on_shutdown
async def stop_relay() -> None:
    stop.set()
    await app.context.get("relay_task")
    await engine.dispose()
