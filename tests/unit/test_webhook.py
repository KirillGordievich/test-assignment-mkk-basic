import json

import httpx
import pytest

from app.services.exc import WebhookDeliveryError
from app.services.webhook import WebhookPayload, WebhookService

URL = "https://merchant.test/webhook"
PAYLOAD = WebhookPayload(payment_id="42", status="succeeded")


def _service(handler: httpx.MockTransport) -> WebhookService:
    return WebhookService(httpx.AsyncClient(transport=handler))


async def test_webhook_is_delivered() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    await _service(httpx.MockTransport(handler)).notify(URL, PAYLOAD)

    assert len(requests) == 1
    assert str(requests[0].url) == URL
    assert json.loads(requests[0].content) == {"payment_id": "42", "status": "succeeded"}


@pytest.mark.parametrize("status_code", [400, 500, 503])
async def test_error_response_raises(status_code: int) -> None:
    service = _service(httpx.MockTransport(lambda _: httpx.Response(status_code)))

    with pytest.raises(WebhookDeliveryError):
        await service.notify(URL, PAYLOAD)


async def test_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(WebhookDeliveryError):
        await _service(httpx.MockTransport(handler)).notify(URL, PAYLOAD)
