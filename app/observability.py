from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('request_id', default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('user_id', default=None)
route_var: contextvars.ContextVar[str | None] = contextvars.ContextVar('route', default=None)


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started_at = time.time()
        self._counters: dict[str, int] = {
            'total_requests': 0,
            'total_errors': 0,
            'auth_failures': 0,
            'rate_limited_requests': 0,
            'publishes_success': 0,
            'publishes_fail': 0,
        }

    def increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counters)
        return {
            'uptime_seconds': round(time.time() - self._started_at, 3),
            'counts': counts,
        }


metrics = Metrics()


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname.lower(),
            'logger': record.name,
            'message': record.getMessage(),
            'route': getattr(record, 'route', None) or route_var.get(),
            'user_id': getattr(record, 'user_id', None) or user_id_var.get(),
            'request_id': getattr(record, 'request_id', None) or request_id_var.get(),
            'status_code': getattr(record, 'status_code', None),
            'duration_ms': getattr(record, 'duration_ms', None),
        }
        for key, value in getattr(record, 'event_data', {}).items():
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return ' '.join(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in payload.items() if value is not None)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, 'request_id'):
            record.request_id = request_id_var.get()
        if not hasattr(record, 'user_id'):
            record.user_id = user_id_var.get()
        if not hasattr(record, 'route'):
            record.route = route_var.get()
        return True


def setup_logging() -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, '_artemis_logging_configured', False):
        return

    level_name = os.getenv('ARTEMIS_LOG_LEVEL')
    if not level_name:
        env = os.getenv('ARTEMIS_ENV', 'dev').lower()
        level_name = 'DEBUG' if env == 'dev' and os.getenv('ARTEMIS_DEBUG', '').lower() in {'1', 'true', 'yes', 'on'} else 'INFO'
    root_logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(KeyValueFormatter())
    context_filter = RequestContextFilter()
    handler.addFilter(context_filter)

    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.addFilter(context_filter)
    root_logger._artemis_logging_configured = True


logger = logging.getLogger('artemis')


SAFE_HEADER_ALLOWLIST = {'user-agent', 'x-request-id', 'content-type', 'content-length'}
SENSITIVE_HEADERS = {'authorization', 'cookie', 'set-cookie'}


def get_request_id(request: Request) -> str:
    header_value = request.headers.get('x-request-id')
    return header_value.strip() if header_value and header_value.strip() else str(uuid4())


def set_user_context(user_id: str | None) -> None:
    user_id_var.set(user_id)


def sanitize_headers(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        normalized = key.lower()
        if normalized in SENSITIVE_HEADERS:
            continue
        if normalized in SAFE_HEADER_ALLOWLIST:
            result[normalized] = value
    return result


def log_event(level: int, message: str, **event_data: Any) -> None:
    extra = {
        'event_data': event_data,
        'status_code': event_data.get('status_code'),
        'duration_ms': event_data.get('duration_ms'),
        'route': event_data.get('route'),
        'path': event_data.get('path'),
        'user_id': event_data.get('user_id'),
        'request_id': event_data.get('request_id'),
    }
    logger.log(level, message, extra=extra)


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = get_request_id(request)
        request_id_var.set(request_id)
        route_var.set(request.url.path)
        user_id_var.set(None)
        request.state.request_id = request_id
        request.state.started_at = time.perf_counter()
        request.state.log_context = {'request_id': request_id, 'route': request.url.path}
        metrics.increment('total_requests')

        log_event(
            logging.INFO,
            'request.started',
            method=request.method,
            route=request.url.path,
            request_id=request_id,
            headers=sanitize_headers(request.headers),
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - request.state.started_at) * 1000, 2)
            log_event(
                logging.ERROR,
                'request.unhandled_exception',
                path=request.url.path,
                request_id=request_id,
                duration_ms=duration_ms,
            )
            raise

        response.headers['X-Request-ID'] = request_id
        duration_ms = round((time.perf_counter() - request.state.started_at) * 1000, 2)
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        log_event(
            level,
            'request.completed',
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    status_code = exc.status_code
    if status_code == 401:
        metrics.increment('auth_failures')
    if status_code >= 500:
        metrics.increment('total_errors')
    level = logging.ERROR if status_code >= 500 else logging.WARNING
    log_event(
        level,
        'http_exception',
        path=request.url.path,
        request_id=getattr(request.state, 'request_id', None),
        status_code=status_code,
        detail=exc.detail,
    )
    error_value = exc.detail if isinstance(exc.detail, str) and exc.detail else 'request_error'
    return JSONResponse(
        status_code=status_code,
        content={'error': error_value, 'request_id': getattr(request.state, 'request_id', None)},
        headers={'X-Request-ID': getattr(request.state, 'request_id', '')},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    metrics.increment('total_errors')
    log_event(
        logging.ERROR,
        'unhandled_exception',
        path=request.url.path,
        request_id=getattr(request.state, 'request_id', None),
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={'error': 'internal_error', 'request_id': getattr(request.state, 'request_id', None)},
        headers={'X-Request-ID': getattr(request.state, 'request_id', '')},
    )


def health_payload() -> dict[str, Any]:
    snapshot = metrics.snapshot()
    counts = snapshot['counts']
    return {
        'ok': counts.get('total_errors', 0) == 0,
        'uptime': snapshot['uptime_seconds'],
        'counts': counts,
    }


def internal_error_response(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={'error': 'internal_error', 'request_id': getattr(request.state, 'request_id', None)},
        headers={'X-Request-ID': getattr(request.state, 'request_id', '')},
    )
