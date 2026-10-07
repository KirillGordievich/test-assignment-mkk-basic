from decimal import Decimal
from typing import Any

import pytest

from app.db import Currency, Payment, PaymentStatus
from app.models import PaymentCreate
from app.services.payment import PaymentService

REQUEST: dict[str, Any] = {
    "amount": "100",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://example.com/webhook",
}


@pytest.fixture
def stored_payment() -> Payment:
    return Payment(
        amount=Decimal("100.00"),
        currency=Currency.RUB,
        description="Order #42",
        metadata_={"order_id": 42},
        webhook_url="https://example.com/webhook",
        status=PaymentStatus.PENDING,
        idempotency_key="key-1",
    )


def test_same_request_matches_stored_payment(stored_payment: Payment) -> None:
    assert PaymentService._is_same_request(stored_payment, PaymentCreate.model_validate(REQUEST))


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "100.01"},
        {"currency": "USD"},
        {"description": "Order #43"},
        {"metadata": {"order_id": 43}},
        {"webhook_url": "https://example.com/other"},
    ],
)
def test_different_request_does_not_match(
    stored_payment: Payment, override: dict[str, Any]
) -> None:
    request = PaymentCreate.model_validate({**REQUEST, **override})

    assert not PaymentService._is_same_request(stored_payment, request)
