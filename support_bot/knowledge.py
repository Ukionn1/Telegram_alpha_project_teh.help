from __future__ import annotations

import re
from difflib import SequenceMatcher

from .db import Database


WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


async def find_faq_answer(db: Database, question: str) -> dict | None:
    normalized = normalize(question)
    if not normalized:
        return None

    best_item = None
    best_score = 0.0
    for item in await db.list_faq():
        keywords = normalize(item["keywords"])
        title = normalize(item["question"])
        score = SequenceMatcher(None, normalized, title).ratio()

        input_words = set(normalized.split())
        keyword_words = set(keywords.split())
        if input_words and keyword_words:
            score += len(input_words & keyword_words) / max(len(input_words), 1)

        if score > best_score:
            best_score = score
            best_item = item

    return best_item if best_item and best_score >= 0.45 else None
