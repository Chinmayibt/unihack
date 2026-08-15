from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup


@dataclass
class ExtractedDocument:
    title: str
    content: str
    page_count: int | None
    links: list[str] = field(default_factory=list)
    document_type: str = "PRODUCT_PAGE"


def _flatten_json_ld(raw: str) -> str:
    import json

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    blobs: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key in ("name", "description", "brand", "sku", "mpn", "category"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    blobs.append(f"{key}: {value.strip()}")
                elif isinstance(value, dict) and value.get("name"):
                    blobs.append(f"{key}: {value['name']}")
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return "\n".join(blobs)


def _clean_space(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_html(html: str | bytes, url: str) -> ExtractedDocument:
    soup = BeautifulSoup(html, "lxml")

    json_ld_bits: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (script.string or "").strip()
        if raw:
            json_ld_bits.append(_flatten_json_ld(raw))

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    heading = soup.find(["h1"])
    if heading and heading.get_text(strip=True):
        title = title or heading.get_text(strip=True)

    meta_bits: list[str] = []
    for key, attr in (("name", "description"), ("property", "og:description"), ("property", "og:title")):
        tag = soup.find("meta", attrs={key: attr})
        content = (tag.get("content") if tag else None) or ""
        if content.strip():
            meta_bits.append(content.strip())

    for tag in soup(["nav", "footer", "header", "form"]):
        tag.decompose()

    parts: list[str] = []
    root = soup.find("main") or soup.find("article") or soup.body or soup
    if title:
        parts.append(title)
    parts.extend(meta_bits)
    parts.extend([bit for bit in json_ld_bits if bit])

    table_text: list[str] = []
    for table in root.find_all("table"):
        rows: list[str] = []
        for row in table.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        if rows:
            table_text.append("\n".join(rows))
        table.decompose()

    visible = root.get_text("\n", strip=True)
    if visible:
        parts.append(visible)
    if table_text:
        parts.append("Specifications\n" + "\n\n".join(table_text))

    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = urljoin(url, anchor["href"])
        if href.startswith("http") and href not in links:
            links.append(href)

    return ExtractedDocument(
        title=title or url,
        content=_clean_space("\n\n".join(parts)),
        page_count=1,
        links=links[:50],
        document_type="PRODUCT_PAGE",
    )


def extract_pdf(data: bytes, url: str) -> ExtractedDocument:
    import fitz

    document = fitz.open(stream=data, filetype="pdf")
    pages: list[str] = []
    for index, page in enumerate(document, start=1):
        text = page.get_text("text") or ""
        if text.strip():
            pages.append(f"Page {index}\n{text.strip()}")
    title = document.metadata.get("title") or url
    document.close()
    return ExtractedDocument(
        title=str(title).strip() or url,
        content=_clean_space("\n\n".join(pages)),
        page_count=len(pages) or None,
        links=[],
        document_type="TECHNICAL_DOCUMENT",
    )


def extract_fetched(content_bytes: bytes, content_type: str, url: str) -> ExtractedDocument:
    is_pdf = "pdf" in content_type or url.lower().split("?")[0].endswith(".pdf")
    if is_pdf:
        return extract_pdf(content_bytes, url)
    html = content_bytes.decode("utf-8", errors="ignore")
    extracted = extract_html(html, url)
    if "pdf" in content_type:
        extracted.document_type = "TECHNICAL_DOCUMENT"
    return extracted
