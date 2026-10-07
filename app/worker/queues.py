"""RabbitMQ topology for payment processing.

Everything goes through a single direct exchange:
- ``payments.new``: main queue; rejected messages dead-letter to ``payments.dlq``;
- ``payments.retry.<delay>ms``: one queue per retry delay, without consumers; messages
  wait for the queue TTL and dead-letter back to ``payments.new``;
- ``payments.dlq``: messages that exhausted retries or failed unexpectedly.
"""

from faststream.rabbit import ExchangeType, RabbitBroker, RabbitExchange, RabbitQueue

from app.config import settings
from app.services.payment import NEW_PAYMENTS_ROUTING_KEY

RETRY_COUNT_HEADER = "x-retry-count"

payments_exchange = RabbitExchange("payments", type=ExchangeType.DIRECT, durable=True)

payments_dlq = RabbitQueue("payments.dlq", durable=True, routing_key="payments.dlq")

payments_queue = RabbitQueue(
    NEW_PAYMENTS_ROUTING_KEY,
    durable=True,
    routing_key=NEW_PAYMENTS_ROUTING_KEY,
    arguments={
        "x-dead-letter-exchange": payments_exchange.name,
        "x-dead-letter-routing-key": payments_dlq.routing_key,
    },
)


def _retry_queue(delay_ms: int) -> RabbitQueue:
    name = f"payments.retry.{delay_ms}ms"
    return RabbitQueue(
        name,
        durable=True,
        routing_key=name,
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": payments_exchange.name,
            "x-dead-letter-routing-key": payments_queue.routing_key,
        },
    )


# A queue per delay rather than per-message TTL: RabbitMQ expires messages only at the
# head of a queue, so a long delay would hold back shorter ones queued behind it.
payments_retry_queues = [
    _retry_queue(settings.consumer.retry_base_delay_ms * 2**retry)
    for retry in range(settings.consumer.max_retries - 1)
]


async def declare_payments_queues(broker: RabbitBroker) -> None:
    exchange = await broker.declare_exchange(payments_exchange)
    for queue in (payments_queue, payments_dlq, *payments_retry_queues):
        declared = await broker.declare_queue(queue)
        await declared.bind(exchange, routing_key=queue.routing_key)
