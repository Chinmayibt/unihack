from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


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


def _search_with_client(client: object, query: str, max_results: int) -> list[SearchHit]:
    try:
        rows = client.text(query, max_results=max_results) or []  # type: ignore[attr-defined]
    except Exception:
        return []
    return _hits_from_rows(rows)


@contextmanager
def web_search_session():
    """One DDGS client for all search_web() calls in the current research run."""
    cls = _ddgs_class()
    if cls is None:
        yield None
        return
    try:
        manager = cls()
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
    """Best-effort web search. Failures return no hits so research can continue."""
    if not query or not query.strip():
        return []
    existing = _active_client.get()
    if existing is not None:
        return _search_with_client(existing, query, max_results)

    cls = _ddgs_class()
    if cls is None:
        return []
    try:
        with cls() as client:
            return _search_with_client(client, query, max_results)
    except Exception:
        return []
