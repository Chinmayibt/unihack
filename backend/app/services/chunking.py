from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass
class TextChunk:
    text: str
    index: int
    page: int | None = None


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[TextChunk]:
    size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap if overlap is not None else settings.CHUNK_OVERLAP
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [TextChunk(text=cleaned, index=0)]

    chunks: list[TextChunk] = []
    start = 0
    index = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        if end < len(cleaned):
            window = cleaned[start:end]
            split_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("\n"))
            if split_at >= size // 3:
                end = start + split_at + 1
        piece = cleaned[start:end].strip()
        if piece:
            page = None
            if piece.startswith("Page "):
                try:
                    page = int(piece.split("\n", 1)[0].replace("Page", "").strip())
                except ValueError:
                    page = None
            chunks.append(TextChunk(text=piece, index=index, page=page))
            index += 1
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks
