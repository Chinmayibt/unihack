from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

SEARCH_TIMEOUT_SECONDS = 8.0


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""


_active_client: ContextVar[object | None] = ContextVar("ddgs_client", default=None)


def _ddgs_class():
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:  # pragma: no cover
        try:
            from duckduckgo_search import DDGS  # type: ignore[no-redef]

            return DDGS
        except ImportError:
            return None


def _hits_from_rows(rows: list[dict] | None) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for row in rows or []:
        url = (row.get("href") or row.get("url") or "").strip()
        if not url:
            continue
        hits.append(
            SearchHit(
                title=(row.get("title") or "").strip(),
                url=url,
                snippet=(row.get("body") or row.get("description") or "").strip(),
            )
        )
    return hits


def _call_with_timeout(func, timeout: float):
    """Return func() or None if it exceeds timeout. Do not wait for hung threads."""
    if timeout <= 0:
        try:
            return func()
        except Exception:
            return None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="search-timeout")
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        return None
    except Exception:
        return None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _search_with_client(client: object, query: str, max_results: int) -> list[SearchHit]:
    rows = _call_with_timeout(
        lambda: client.text(query, max_results=max_results) or [],  # type: ignore[attr-defined]
        SEARCH_TIMEOUT_SECONDS,
    )
    if not rows:
        return []
    return _hits_from_rows(rows)


def _open_ddgs():
    cls = _ddgs_class()
    if cls is None:
        return None
    try:
        return cls(timeout=max(1, int(SEARCH_TIMEOUT_SECONDS)))
    except TypeError:
        return cls()


@contextmanager
def web_search_session():
    """One DDGS client for all search_web() calls in the current research run."""
    manager = _open_ddgs()
    if manager is None:
        yield None
        return
    try:
        client = manager.__enter__()
    except Exception:
        yield None
        return
    token = _active_client.set(client)
    try:
        yield client
    finally:
        _active_client.reset(token)
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass


def search_web(query: str, max_results: int = 8) -> list[SearchHit]:
    """Best-effort web search. Failures and hangs return no hits so research can continue."""
    if not query or not query.strip():
        return []
    existing = _active_client.get()
    if existing is not None:
        return _search_with_client(existing, query, max_results)

    manager = _open_ddgs()
    if manager is None:
        return []
    try:
        with manager as client:
            return _search_with_client(client, query, max_results)
    except Exception:
        return []
