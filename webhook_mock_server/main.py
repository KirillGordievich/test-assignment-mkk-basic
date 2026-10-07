import logging

from fastapi import FastAPI, Query, Request, Response

# Standalone on purpose: importing app.config would require DB and API key settings.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("webhook_mock_server")

app = FastAPI(title="Webhook mock server", docs_url=None, redoc_url=None, openapi_url=None)


@app.post("/webhook")
async def receive_webhook(
    request: Request,
    status: int = Query(default=200, ge=200, le=599, description="Status code to respond with"),
) -> Response:
    body = (await request.body()).decode(errors="replace")
    logger.info("Webhook received: %s (responding %d)", body, status)
    return Response(status_code=status)
