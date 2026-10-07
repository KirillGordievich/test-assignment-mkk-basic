import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from app.services.exc import WebhookDeliveryError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    payment_id: str
    status: str


class WebhookService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def notify(self, webhook_url: str, payload: WebhookPayload) -> None:
        try:
            response = await self._client.post(
                webhook_url,
                json={"payment_id": payload.payment_id, "status": payload.status},
                timeout=settings.consumer.webhook_timeout_s,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise WebhookDeliveryError(f"Webhook to {webhook_url} failed: {error!r}") from error

        logger.info("Webhook delivered to %s for payment %s", webhook_url, payload.payment_id)
