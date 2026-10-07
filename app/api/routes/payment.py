import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.deps.auth import verify_api_key
from app.deps.db import PaymentServiceDep
from app.models import PaymentCreate, PaymentCreated, PaymentRead
from app.services.exc import IdempotencyKeyConflictError

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(verify_api_key)],
)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_payment(
    data: PaymentCreate,
    service: PaymentServiceDep,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255)],
) -> PaymentCreated:
    try:
        payment = await service.create(idempotency_key, data)
    except IdempotencyKeyConflictError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Idempotency-Key has already been used with a different request body",
        ) from None
    return PaymentCreated.model_validate(payment)


@router.get("/{payment_id}")
async def get_payment(
    payment_id: uuid.UUID,
    service: PaymentServiceDep,
) -> PaymentRead:
    payment = await service.get(payment_id)
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentRead.model_validate(payment)
