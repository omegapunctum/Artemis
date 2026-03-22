from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from time import time

from fastapi import HTTPException, Request, status

from app.observability import log_event, metrics

rate_limit_store: dict[str, list[float]] = {}
rate_limit_lock = threading.Lock()
login_failure_store: dict[str, list[float]] = {}
login_block_store: dict[str, float] = {}


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_ip = forwarded_for.split(",", 1)[0].strip()
        if first_ip:
            return first_ip
    client = request.client
    return client.host if client else "unknown"


def _prune_timestamps(timestamps: list[float], window_seconds: int, now: float) -> list[float]:
    threshold = now - window_seconds
    return [timestamp for timestamp in timestamps if timestamp > threshold]


def _rate_limit_key(prefix: str, request: Request, include_path: bool) -> str:
    ip = get_client_ip(request)
    if include_path:
        return f"{prefix}:{ip}:{request.url.path}"
    return f"{prefix}:{ip}"


def _raise_rate_limited(request: Request) -> None:
    ip = get_client_ip(request)
    metrics.increment('rate_limited_requests')
    log_event(
        logging.WARNING,
        'rate_limit.blocked_request',
        route=request.url.path,
        request_id=getattr(getattr(request, 'state', None), 'request_id', None),
        endpoint=request.url.path,
        ip=ip,
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")


def rate_limit(limit: int, window_seconds: int, *, prefix: str = "rl", include_path: bool = False) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        now = time()
        key = _rate_limit_key(prefix, request, include_path)
        with rate_limit_lock:
            timestamps = _prune_timestamps(rate_limit_store.get(key, []), window_seconds, now)
            if len(timestamps) >= limit:
                rate_limit_store[key] = timestamps
                _raise_rate_limited(request)
            timestamps.append(now)
            rate_limit_store[key] = timestamps

    return dependency


def check_login_block(request: Request) -> None:
    now = time()
    key = _rate_limit_key("login-fail", request, include_path=False)
    with rate_limit_lock:
        blocked_until = login_block_store.get(key)
        if blocked_until and blocked_until > now:
            _raise_rate_limited(request)
        if blocked_until and blocked_until <= now:
            login_block_store.pop(key, None)
            login_failure_store.pop(key, None)


def register_login_failure(request: Request, *, limit: int = 5, window_seconds: int = 60, block_seconds: int = 60) -> None:
    now = time()
    key = _rate_limit_key("login-fail", request, include_path=False)
    with rate_limit_lock:
        failures = _prune_timestamps(login_failure_store.get(key, []), window_seconds, now)
        failures.append(now)
        login_failure_store[key] = failures
        if len(failures) >= limit:
            login_block_store[key] = now + block_seconds


def reset_login_failures(request: Request) -> None:
    key = _rate_limit_key("login-fail", request, include_path=False)
    with rate_limit_lock:
        login_failure_store.pop(key, None)
        login_block_store.pop(key, None)
