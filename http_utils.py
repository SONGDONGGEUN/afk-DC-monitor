"""Small HTTP helpers shared by DC and Naver scrapers."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

import requests

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    backoff_seconds: tuple[float, ...] = (1.0, 3.0),
    label: str = "request",
) -> T:
    """Run fn with retries on requests-level transient errors.

    Retries on Timeout, ConnectionError, and 5xx responses. Other errors
    (auth, 4xx, ValueError, etc.) propagate immediately because retrying
    them won't help.
    """
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except (requests.Timeout, requests.ConnectionError) as e:
            last_exc = e
            print(f"  [retry] {label}: attempt {i + 1}/{attempts} failed ({type(e).__name__})")
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if 500 <= status < 600:
                last_exc = e
                print(f"  [retry] {label}: attempt {i + 1}/{attempts} got {status}")
            else:
                raise
        if i < attempts - 1:
            time.sleep(backoff_seconds[min(i, len(backoff_seconds) - 1)])
    assert last_exc is not None
    raise last_exc
