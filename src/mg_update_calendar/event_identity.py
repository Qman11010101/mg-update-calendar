from __future__ import annotations

import hashlib
import json
import unicodedata

from mg_update_calendar.models import Article, Entry


def normalize_event_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def event_id(entry: Entry, article: Article) -> str | None:
    if (not entry.event_name or not entry.event_evidence or entry.confidence < 0.8
            or entry.service not in (article.game, "card_maker")
            or entry.start is None or entry.end is None or entry.start > entry.end
            or entry.open_ended or entry.start_is_deadline):
        return None
    if (entry.start == entry.end and entry.start_time and entry.end_time
            and entry.start_time > entry.end_time):
        return None
    name = normalize_event_name(entry.event_name)
    if not name or name not in normalize_event_name(entry.event_evidence):
        return None
    if not any(entry.event_evidence in source for source in (
            article.title, article.body_text, article.body_markdown)):
        return None
    # 記事の処理順や出典URLが変わっても、同じ開催回のIDを保つ。
    identity = [article.game, entry.service, name, entry.start.isoformat(), entry.start_time,
                entry.end.isoformat(), entry.end_time]
    payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return "evt_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
