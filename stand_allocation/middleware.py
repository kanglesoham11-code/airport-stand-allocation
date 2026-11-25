"""HTTP request pipeline (section 10A.4).

Request ID, timer, GENERAL rate limit, auth, route, response headers and the
access log. Implemented as a Starlette BaseHTTPMiddleware.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from stand_allocation import config, security
from stand_allocation.ratelimit import AUTH_FAILURE_RULE, GENERAL_RULE
from stand_allocation.security import key_fingerprint, key_matches

REQUEST_ID_RE = re.compile(config.REQUEST_ID_PATTERN)
logger = logging.getLogger("stand_allocation.access")


class RequestPipelineMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: Any,
        general_store: Any,
        failure_store: Any,
        counters: Any,
        run_id: str | None,
    ) -> None:
        super().__init__(app)
        self._general_store = general_store
        self._failure_store = failure_store
        self._counters = counters
        self._run_id = run_id

    def _client_ip(self, request: Request) -> str:
        if config.TRUST_PROXY_HEADERS and "x-forwarded-for" in request.headers:
            return request.headers["x-forwarded-for"].split(",")[-1].strip()
        return request.client.host if request.client else "unknown"

    def _route_template(self, request: Request) -> str:
        for route in request.app.router.routes:
            match, _ = route.matches(request.scope)
            if match == Match.FULL:
                template = getattr(route, "path_template", None)
                if template:
                    return template
        return "unmatched"

    def _error_response(
        self,
        request_id: str,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        h: dict[str, str] = {
            "X-Request-ID": request_id,
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if headers:
            h.update(headers)
        return JSONResponse(
            {"error": {"code": code, "message": message, "request_id": request_id}},
            status_code=status_code,
            headers=h,
        )

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or ""
        if not REQUEST_ID_RE.fullmatch(request_id):
            request_id = uuid.uuid4().hex
        request.state.request_id = request_id

        started = time.monotonic()
        request.state.start_time = started
        path = request.url.path
        method = request.method.upper()
        now = started

        # Content-Length validation (section 10A.6).
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                cl = int(content_length)
            except ValueError:
                return self._error_response(
                    request_id, 400, "BAD_REQUEST", "Invalid request parameters."
                )
            if cl < 0:
                return self._error_response(
                    request_id, 400, "BAD_REQUEST", "Invalid request parameters."
                )
            if method == "GET" and cl > 0:
                return self._error_response(
                    request_id, 413, "PAYLOAD_TOO_LARGE", "Request body too large."
                )

        remaining: int | None = None
        reset: int | None = None

        # Health and readiness skip every limit and the key check.
        if path not in ("/health", "/ready"):
            client_ip = self._client_ip(request)
            allowed, remaining, reset, retry = self._general_store.take(
                client_ip, GENERAL_RULE, now
            )
            if not allowed:
                self._counters.record_rate_limited()
                return self._rate_limited_response(request_id, retry, remaining, reset)

            if path not in config.AUTH_FREE_PATHS:
                if (
                    self._failure_store.available(client_ip, AUTH_FAILURE_RULE, now)
                    < 1.0
                ):
                    retry = self._failure_store.take(
                        client_ip, AUTH_FAILURE_RULE, now
                    )[3]
                    self._counters.record_rate_limited()
                    return JSONResponse(
                        {
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": "Too many requests.",
                                "request_id": request_id,
                            }
                        },
                        status_code=429,
                        headers={"Retry-After": str(retry), "X-Request-ID": request_id},
                    )
                key = request.headers.get("x-api-key")
                if not key_matches(key, config.API_KEYS):
                    self._failure_store.take(client_ip, AUTH_FAILURE_RULE, now)
                    self._counters.record_auth_failed()
                    return JSONResponse(
                        {
                            "error": {
                                "code": "UNAUTHORIZED",
                                "message": "Invalid or missing API key.",
                                "request_id": request_id,
                            }
                        },
                        status_code=401,
                        headers={
                            "WWW-Authenticate": 'ApiKey realm="stand-allocation"',
                            "X-Request-ID": request_id,
                        },
                    )

        try:
            response = await call_next(request)
        except StarletteHTTPException as exc:
            if isinstance(exc.detail, dict) and "code" in exc.detail:
                code = exc.detail["code"]
                message = exc.detail["message"]
            else:
                code_map = {
                    404: "NOT_FOUND",
                    405: "METHOD_NOT_ALLOWED",
                    422: "VALIDATION_ERROR",
                }
                code = code_map.get(exc.status_code, "ERROR")
                message = str(exc.detail)
            response = self._error_response(
                request_id, exc.status_code, code, message, exc.headers
            )
            status_code = exc.status_code
        else:
            status_code = response.status_code

        # ETag for cacheable 200s (section 10A.5).
        cacheable = (
            path == "/allocations"
            or path == "/stands"
            or path == "/data-issues"
            or path == "/metrics"
            or path.startswith("/stands/")
        )
        if status_code == 200 and cacheable and self._run_id:
            query = request.url.query
            path_and_query = path + ("?" + query if query else "")
            etag = security.etag_for(self._run_id, path_and_query)
            if_none_match = request.headers.get("if-none-match")
            if if_none_match and security.etag_matches(if_none_match, etag):
                return JSONResponse(
                    {},
                    status_code=304,
                    headers={"ETag": etag, "X-Request-ID": request_id},
                )
            response.headers["ETag"] = etag

        self._apply_headers(response, request_id, remaining, reset)
        self._log(request, path, status_code, started, remaining is not None)
        return response

    def _apply_headers(
        self,
        response: Response,
        request_id: str,
        remaining: int | None,
        reset: int | None,
    ) -> None:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if remaining is not None and reset is not None:
            response.headers["X-RateLimit-Limit"] = str(config.RATE_LIMIT_CAPACITY)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset)

    def _rate_limited_response(
        self, request_id: str, retry: int, remaining: int, reset: int
    ) -> JSONResponse:
        headers = {
            "Retry-After": str(retry),
            "X-Request-ID": request_id,
            "X-RateLimit-Limit": str(config.RATE_LIMIT_CAPACITY),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset),
        }
        return JSONResponse(
            {
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Too many requests. Try again in "
                    + str(retry)
                    + " seconds.",
                    "request_id": request_id,
                }
            },
            status_code=429,
            headers=headers,
        )

    def _log(
        self,
        request: Request,
        path: str,
        status_code: int,
        started: float,
        rate_limited: bool,
    ) -> None:
        duration_ms = (time.monotonic() - started) * 1000.0
        status_class = f"{status_code // 100}xx"
        self._counters.record_request(status_class, duration_ms / 1000.0)
        client_ip = self._client_ip(request)
        if status_code in (401, 429):
            level = logging.WARNING
        elif status_code >= 500:
            level = logging.ERROR
        else:
            level = logging.INFO
        logger.log(
            level,
            "request",
            extra={
                "run_id": self._run_id,
                "request_id": request.state.request_id,
                "route": self._route_template(request),
                "method": request.method,
                "path": path,
                "status": status_code,
                "status_class": status_class,
                "client_ip": client_ip,
                "duration_ms": round(duration_ms, 1),
                "rate_limited": rate_limited,
                "key_fingerprint": key_fingerprint(
                    request.headers.get("x-api-key", "")
                )
                if path not in config.AUTH_FREE_PATHS
                and path not in ("/health", "/ready")
                else None,
            },
        )


__all__ = ["RequestPipelineMiddleware"]
