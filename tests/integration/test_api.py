import asyncio
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Base, OutboxEvent, Payment

PAYMENT: dict[str, Any] = {
    "amount": "100.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "https://example.com/webhook",
}

SessionFactory = async_sessionmaker[AsyncSession]


async def _count(session_factory: SessionFactory, model: type[Base]) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


async def test_create_payment(client: AsyncClient, session_factory: SessionFactory) -> None:
    response = await client.post(
        "/api/v1/payments", json=PAYMENT, headers={"Idempotency-Key": "key-1"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert set(body) == {"payment_id", "status", "created_at"}

    async with session_factory() as session:
        event = await session.scalar(select(OutboxEvent))
    assert event is not None
    assert event.routing_key == "payments.new"
    assert event.payload == {"payment_id": body["payment_id"]}


async def test_repeated_request_returns_same_payment(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    headers = {"Idempotency-Key": "key-1"}

    first = await client.post("/api/v1/payments", json=PAYMENT, headers=headers)
    second = await client.post("/api/v1/payments", json=PAYMENT, headers=headers)

    assert second.status_code == 202
    assert second.json() == first.json()
    assert await _count(session_factory, Payment) == 1
    assert await _count(session_factory, OutboxEvent) == 1


async def test_concurrent_requests_create_single_payment(
    client: AsyncClient, session_factory: SessionFactory
) -> None:
    responses = await asyncio.gather(
        *(
            client.post("/api/v1/payments", json=PAYMENT, headers={"Idempotency-Key": "key-1"})
            for _ in range(10)
        )
    )

    assert {response.status_code for response in responses} == {202}
    assert len({response.json()["payment_id"] for response in responses}) == 1
    assert await _count(session_factory, Payment) == 1
    assert await _count(session_factory, OutboxEvent) == 1


async def test_reused_key_with_different_body_is_rejected(client: AsyncClient) -> None:
    headers = {"Idempotency-Key": "key-1"}
    await client.post("/api/v1/payments", json=PAYMENT, headers=headers)

    response = await client.post(
        "/api/v1/payments", json={**PAYMENT, "amount": "200"}, headers=headers
    )

    assert response.status_code == 409


async def test_idempotency_key_is_required(client: AsyncClient) -> None:
    response = await client.post("/api/v1/payments", json=PAYMENT)

    assert response.status_code == 422


async def test_get_payment(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/payments", json=PAYMENT, headers={"Idempotency-Key": "key-1"}
    )
    payment_id = created.json()["payment_id"]

    response = await client.get(f"/api/v1/payments/{payment_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == payment_id
    assert body["amount"] == "100.50"
    assert body["currency"] == "RUB"
    assert body["metadata"] == {"order_id": 42}
    assert body["status"] == "pending"
    assert body["processed_at"] is None


async def test_get_unknown_payment_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/payments/{uuid.uuid4()}")

    assert response.status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
async def test_requests_without_valid_api_key_are_rejected(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    client.headers.pop("X-API-Key")
    client.headers.update(headers)

    create = await client.post(
        "/api/v1/payments", json=PAYMENT, headers={"Idempotency-Key": "key-1"}
    )
    get = await client.get(f"/api/v1/payments/{uuid.uuid4()}")

    assert create.status_code == 401
    assert get.status_code == 401
