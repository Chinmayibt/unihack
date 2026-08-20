from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.core.config import settings
from app.services.chat_llm import advance_provider_on_quota

T = TypeVar("T")

LLM_QUOTA_EXHAUSTED = "LLM_QUOTA_EXHAUSTED"
LLM_RATE_LIMIT_TPM = "LLM_RATE_LIMIT_TPM"

_RETRY_AFTER = re.compile(
    r"try again in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:([0-9.]+)\s*s)?",
    re.IGNORECASE,
)
_RATE_LIMIT_LOCK = threading.Lock()
_LLM_CALL_LOCK = threading.Lock()
_RATE_LIMIT_UNTIL = 0.0
_THREAD_METRICS = threading.local()


@dataclass
class LlmCallMetrics:
    llm_request_ms: float = 0.0
    llm_wait_ms: float = 0.0
    llm_cooldown_ms: float = 0.0
    llm_attempts: int = 0


def last_llm_call_metrics() -> LlmCallMetrics:
    payload = getattr(_THREAD_METRICS, "last", None)
    if payload is None:
        return LlmCallMetrics()
    return LlmCallMetrics(
        llm_request_ms=payload.llm_request_ms,
        llm_wait_ms=payload.llm_wait_ms,
        llm_cooldown_ms=payload.llm_cooldown_ms,
        llm_attempts=payload.llm_attempts,
    )


def reset_llm_call_metrics() -> None:
    _store_metrics(LlmCallMetrics())


def _store_metrics(metrics: LlmCallMetrics) -> None:
    _THREAD_METRICS.last = metrics


def is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "429" in text or "rate_limit" in text or "rate limit" in text


def is_daily_token_limit(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "tokens per day" in text
        or "tpd" in text
        or "insufficient credits" in text
        or "credit limit" in text
        or "quota exceeded" in text
        or "usage limit" in text
    )


def retry_delay_seconds(exc: BaseException, attempt: int) -> float:
    match = _RETRY_AFTER.search(str(exc))
    if match:
        hours = float(match.group(1) or 0)
        minutes = float(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        delay = hours * 3600.0 + minutes * 60.0 + seconds + 0.25
        cap = 120.0 if is_daily_token_limit(exc) else 60.0
        return min(delay, cap)
    return min(2**attempt, 40.0)


def classify_llm_error(exc: BaseException) -> str:
    text = str(exc).lower()
    if is_daily_token_limit(exc):
        return LLM_QUOTA_EXHAUSTED
    if is_rate_limit_error(exc):
        return LLM_RATE_LIMIT_TPM
    if "timeout" in text or "timed out" in text:
        return "LLM_TIMEOUT"
    if "connection refused" in text or "errno 61" in text:
        return "CONNECTION_REFUSED"
    if "validation error" in text or "json" in text or "output parser" in text:
        return "LLM_PARSE"
    return type(exc).__name__


def should_retry_rate_limit(exc: BaseException) -> bool:
    """TPM waits are recoverable. Daily token limits will not recover during a job."""
    return is_rate_limit_error(exc) and not is_daily_token_limit(exc)


def call_with_rate_limit_retry(func: Callable[[], T]) -> T:
    """Serialize Groq calls across workers so two 5k-token extractions cannot overlap TPM."""
    return invoke_with_llm_metrics(
        func,
        serialize=not settings.TESTING,
        apply_cooldown=not settings.TESTING,
    )


def invoke_with_llm_metrics(
    func: Callable[[], T],
    *,
    serialize: bool,
    apply_cooldown: bool,
) -> T:
    wait_started = time.perf_counter()
    if not serialize:
        return _call_with_retries(func, wait_ms=0.0, apply_cooldown=apply_cooldown)
    _LLM_CALL_LOCK.acquire()
    wait_ms = (time.perf_counter() - wait_started) * 1000.0
    try:
        return _call_with_retries(func, wait_ms=wait_ms, apply_cooldown=apply_cooldown)
    finally:
        _LLM_CALL_LOCK.release()


def _call_with_retries(
    func: Callable[[], T],
    *,
    wait_ms: float,
    apply_cooldown: bool,
) -> T:
    global _RATE_LIMIT_UNTIL
    attempts_allowed = max(1, settings.LLM_RATE_LIMIT_RETRIES)
    last_error: BaseException | None = None
    request_ms = 0.0
    cooldown_ms = 0.0
    attempts = 0
    try:
        for attempt in range(attempts_allowed):
            attempts = attempt + 1
            if apply_cooldown:
                with _RATE_LIMIT_LOCK:
                    wait = _RATE_LIMIT_UNTIL - time.time()
                if wait > 0:
                    slept = time.perf_counter()
                    time.sleep(wait)
                    cooldown_ms += (time.perf_counter() - slept) * 1000.0
            try:
                started = time.perf_counter()
                result = func()
                request_ms += (time.perf_counter() - started) * 1000.0
                return result
            except Exception as exc:
                request_ms += (time.perf_counter() - started) * 1000.0
                last_error = exc
                if is_daily_token_limit(exc) and advance_provider_on_quota():
                    continue
                if not should_retry_rate_limit(exc) or attempt >= attempts_allowed - 1:
                    raise
                delay = retry_delay_seconds(exc, attempt) if apply_cooldown else 0.0
                if delay > 0:
                    with _RATE_LIMIT_LOCK:
                        _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, time.time() + delay)
                    slept = time.perf_counter()
                    time.sleep(delay)
                    cooldown_ms += (time.perf_counter() - slept) * 1000.0
        assert last_error is not None
        raise last_error
    finally:
        _store_metrics(
            LlmCallMetrics(
                llm_request_ms=round(request_ms, 3),
                llm_wait_ms=round(wait_ms, 3),
                llm_cooldown_ms=round(cooldown_ms, 3),
                llm_attempts=attempts,
            )
        )
