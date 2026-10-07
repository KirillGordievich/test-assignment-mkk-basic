from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.db import Currency
from app.models import PaymentCreate

VALID_PAYMENT: dict[str, Any] = {
    "amount": "100.50",
    "currency": "USD",
    "description": "Order #42",
    "webhook_url": "https://example.com/webhook",
}


def test_valid_payment() -> None:
    payment = PaymentCreate.model_validate(VALID_PAYMENT)

    assert payment.amount == Decimal("100.50")
    assert payment.currency is Currency.USD
    assert payment.metadata == {}


@pytest.mark.parametrize(
    "override",
    [
        {"amount": "0"},
        {"amount": "-1"},
        {"amount": "10.001"},
        {"amount": "1" * 17},
        {"currency": "GBP"},
        {"currency": "rub"},
        {"description": "x" * 1001},
        {"webhook_url": "not-a-url"},
        {"metadata": ["not", "an", "object"]},
    ],
)
def test_invalid_payment(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({**VALID_PAYMENT, **override})
