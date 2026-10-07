import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # ServerErrorMiddleware turns any exception that gets here into a 500.
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception("%s %s 500 (%dms)", request.method, request.url.path, elapsed_ms)
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %s (%dms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response
