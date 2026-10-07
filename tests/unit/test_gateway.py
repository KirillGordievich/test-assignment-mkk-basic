import uuid
from collections.abc import Iterator

import pytest

from app.services import payment_gateway
from app.services.exc import PaymentProcessingError
from app.services.payment_gateway import PaymentGateway

SUCCESS, FAILURE = 0.9, 0.0  # random.random() values against a 0.5 failure rate
PAYMENT_1, PAYMENT_2 = uuid.uuid4(), uuid.uuid4()


def _gateway(failure_rate: float) -> PaymentGateway:
    return PaymentGateway(failure_rate=failure_rate, min_delay_s=0, max_delay_s=0)


def _roll(monkeypatch: pytest.MonkeyPatch, *values: float) -> None:
    rolls: Iterator[float] = iter(values)
    monkeypatch.setattr(payment_gateway.random, "random", lambda: next(rolls))


async def test_processing_succeeds_when_failure_rate_is_zero() -> None:
    await _gateway(failure_rate=0).process_payment(PAYMENT_1)


async def test_processing_fails_when_failure_rate_is_one() -> None:
    with pytest.raises(PaymentProcessingError):
        await _gateway(failure_rate=1).process_payment(PAYMENT_1)


async def test_repeated_payment_returns_original_result(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _gateway(failure_rate=0.5)
    _roll(monkeypatch, SUCCESS, FAILURE)

    await gateway.process_payment(PAYMENT_1)
    # Would fail if it were processed again.
    await gateway.process_payment(PAYMENT_1)


async def test_failed_attempt_is_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _gateway(failure_rate=0.5)
    _roll(monkeypatch, FAILURE, SUCCESS)

    with pytest.raises(PaymentProcessingError):
        await gateway.process_payment(PAYMENT_1)
    await gateway.process_payment(PAYMENT_1)


async def test_different_payments_are_processed_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    gateway = _gateway(failure_rate=0.5)
    _roll(monkeypatch, SUCCESS, FAILURE)

    await gateway.process_payment(PAYMENT_1)
    with pytest.raises(PaymentProcessingError):
        await gateway.process_payment(PAYMENT_2)
