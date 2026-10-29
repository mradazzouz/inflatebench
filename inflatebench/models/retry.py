"""Retries with exponential backoff and jitter for transient provider errors."""

from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS = frozenset({408, 409, 425, 429})


def is_retryable(exc: BaseException) -> bool:
    """Rate limits, overload, server errors, timeouts and dropped connections."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None) or getattr(exc, "code", None)
    if isinstance(status, int):
        return status in RETRYABLE_STATUS or status >= 500
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # anthropic.APIConnectionError / APITimeoutError carry no status code.
    return any(c.__name__ in ("APIConnectionError", "APITimeoutError") for c in type(exc).__mro__)


def retry(
    fn: Callable[[], T],
    *,
    attempts: int = 6,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable: Callable[[BaseException], bool] = is_retryable,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying transient failures up to `attempts` times in total."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts - 1 or not retryable(exc):
                raise
            delay = min(max_delay, base_delay * 2**attempt) * random.uniform(0.5, 1.0)
            log.warning("attempt %d/%d failed (%s); retrying in %.1fs", attempt + 1, attempts, exc, delay)
            sleep(delay)
    raise AssertionError("unreachable")
