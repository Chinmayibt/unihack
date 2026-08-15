from __future__ import annotations

from dataclasses import dataclass

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Dead connections should fail quickly. Slow-but-alive manufacturer pages still
# get a moderate read window. Combined worst-case is less than the old 20s cap.
FETCH_CONNECT_TIMEOUT = 5.0
FETCH_READ_TIMEOUT = 10.0


def fetch_timeout(timeout: float | httpx.Timeout | None = None) -> httpx.Timeout:
    if isinstance(timeout, httpx.Timeout):
        return timeout
    if timeout is not None:
        return httpx.Timeout(timeout)
    return httpx.Timeout(
        connect=FETCH_CONNECT_TIMEOUT,
        read=FETCH_READ_TIMEOUT,
        write=FETCH_READ_TIMEOUT,
        pool=FETCH_CONNECT_TIMEOUT,
    )


@dataclass
class FetchedDocument:
    url: str
    content_bytes: bytes
    content_type: str
    final_url: str


def fetch_url(url: str, timeout: float | httpx.Timeout | None = None) -> FetchedDocument:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"}
    with httpx.Client(follow_redirects=True, timeout=fetch_timeout(timeout), headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        return FetchedDocument(
            url=url,
            content_bytes=response.content,
            content_type=content_type or "application/octet-stream",
            final_url=str(response.url),
        )
