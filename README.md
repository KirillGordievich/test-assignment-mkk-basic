# Payments Service

Test assignment for the Python Developer position at MKK Basic.
Task description: [Тестовое PYTHON .pdf](./Тестовое%20PYTHON%20.pdf)

A small service that accepts payments over HTTP, processes them asynchronously through an
emulated payment gateway and reports the result to the merchant's webhook.

Stack: FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), PostgreSQL, RabbitMQ via FastStream,
Alembic, Docker Compose.

## Requirements

* Python 3.12+
* uv
* Docker & Docker Compose

## Running with Docker (recommended)

The compose file reads its settings from `.env-docker`. The example is already set up for
Docker, so just copy it and start everything:

```bash
cp .env.example .env-docker
docker compose up -d --build   # or: make up
```

To also start the webhook mock server (see [Webhook](#webhook)):

```bash
docker compose --profile mock up -d --build   # or: make up-mock
```

## Running locally

For local runs the app reads `.env`. Copy the example and change the hosts to `localhost`:
`POSTGRES_HOST=localhost` and `RABBITMQ_HOST=localhost`.

```bash
cp .env.example .env
make install      # uv sync --dev
make infra-up     # postgres + rabbitmq in Docker
make migrate
```

Then start each process in its own terminal:

```bash
make api
make relay
make consumer
```

## API

Every endpoint under `/api/v1` requires the `X-API-Key` header.

### Create a payment

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H 'X-API-Key: dev-api-key' \
  -H 'Idempotency-Key: order-42' \
  -H 'Content-Type: application/json' \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Order #42",
    "metadata": {"order_id": 42},
    "webhook_url": "http://webhook-mock-server:9000/webhook"
  }'
```

```http
HTTP/1.1 202 Accepted

{
  "payment_id": "0b9a6d8e-6a0e-4a8b-9a43-2f3f6c1d6c10",
  "status": "pending",
  "created_at": "2026-10-07T12:00:00.000000Z"
}
```

`Idempotency-Key` is required. Sending the same key with the same body again returns the
same payment instead of creating a new one. Sending the same key with a different body
returns `409 Conflict`.

Validation: `amount` is positive with at most 2 decimal places, `currency` is one of `RUB`,
`USD`, `EUR`, `metadata` is an optional JSON object, `webhook_url` must be an HTTP(S) URL.

### Get a payment

```bash
curl http://localhost:8000/api/v1/payments/0b9a6d8e-6a0e-4a8b-9a43-2f3f6c1d6c10 \
  -H 'X-API-Key: dev-api-key'
```

```json
{
  "id": "0b9a6d8e-6a0e-4a8b-9a43-2f3f6c1d6c10",
  "amount": "100.50",
  "currency": "RUB",
  "description": "Order #42",
  "metadata": {"order_id": 42},
  "status": "succeeded",
  "webhook_url": "http://webhook-mock-server:9000/webhook",
  "created_at": "2026-10-07T12:00:00.000000Z",
  "processed_at": "2026-10-07T12:00:04.000000Z"
}
```

Status is `pending` until the consumer finishes, then `succeeded` or `failed`.

### Webhook

Once the payment is processed, the consumer sends a `POST` to `webhook_url`:

```json
{"payment_id": "0b9a6d8e-6a0e-4a8b-9a43-2f3f6c1d6c10", "status": "succeeded"}
```

Any 2xx response counts as delivered. The same webhook can arrive more than once, so the
receiver should treat it as idempotent by `payment_id` and `status`.

For local testing, `webhook-mock-server` (port 9000) logs every webhook it receives. It is
optional: start it with `make up-mock` (`docker compose --profile mock up -d`) and use
`http://webhook-mock-server:9000/webhook`, or with `make webhook-mock-server` and use
`http://localhost:9000/webhook`. Add `?status=500` to make it fail and trigger retries.

### Postman

`payments-service.postman_collection.json` and `payments-service.postman_environment.json`
cover the happy path, idempotent replay, 409, 401 and 404. Run the whole collection: each
request checks its own status code.

## Tests

```bash
make test               # everything
make test-unit          # no external dependencies
make test-integration   # needs Docker: starts Postgres via testcontainers
make check              # ruff + mypy + all tests
```

Unit tests cover validation, API key checks, the gateway, webhook delivery and the consumer's
retry/DLQ routing (with FastStream's test broker). Integration tests run the API and the
payment processor against a real Postgres: idempotency under concurrent requests, outbox rows,
redelivery of processed payments, failed webhooks.
