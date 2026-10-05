from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
import unicodedata

from dotenv import load_dotenv
from pydantic import ValidationError

from mg_update_calendar.models import (
    Article, Entry, Cancellation, Extraction,
    Game, GAME_ENTRY_TYPES, ENTRY_LABELS, SONG_TYPES, CONTENT_TYPES, display_title, extraction_schema, subject_key,
)
from mg_update_calendar.llm import JSONGenerator, LLMClient, LLMConfig, LLMError, LLMRequest
from mg_update_calendar.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from mg_update_calendar.services import SERVICE_MAINTENANCE, calendar_dates, maintenance_for

MAX_OUTPUT_TOKENS = 32768
CONCURRENCY = 5
MAX_EXTRACTION_ATTEMPTS = 3
SCHEMA_VERSION = 7
# 前回の結果として読み込める版。6は記事ごとのプロバイダー・モデルを持たない。
READABLE_SCHEMA_VERSIONS = (6, 7)
# 改行・空白の入り方やMarkdown記法の有無は原文根拠かどうかに関係しないため、照合前に取り除く。
QUOTE_NOISE = re.compile(r"[\s#*_>`|\\-]+")
# 対象名末尾の弾数の表記（第2弾、ちほー2、Part2）。作品名と弾数に分けて比べる。
GENERATION = re.compile(r"(?:第([0-9一二三四五六七八九]+)弾|ちほー([0-9]*)|Part([0-9]+))$", re.IGNORECASE)
KANJI_DIGITS = str.maketrans("一二三四五六七八九", "123456789")
CHIHO_NAME = re.compile(r"ちほー[0-9]*$")


class ExtractionError(Exception):
    def __init__(self, code: str, details: list[dict[str, Any]] | None = None):
        super().__init__(code)
        self.details = details or []


def build_request(article: Article, max_output_tokens: int) -> LLMRequest:
    services = (article.game, "card_maker")
    service_context = "\n対象サービスの通常メンテナンス（国内版・日本時間）:\n" + "\n".join(
        f"{service}: {SERVICE_MAINTENANCE[service].start}〜{SERVICE_MAINTENANCE[service].end}"
        if service in SERVICE_MAINTENANCE else f"{service}: 未確認。日付補正不可" for service in services
    )
    return LLMRequest(
        instructions=SYSTEM_PROMPT + "\n対象ゲーム: " + article.game + "\n許可される種類:\n" + "\n".join(
            f"{kind}: {ENTRY_LABELS[kind]}" for kind in GAME_ENTRY_TYPES[article.game]) + service_context,
        input=json.dumps(article.model_dump(mode="json"), ensure_ascii=False),
        schema=extraction_schema(article.game),
        schema_name="news_entries",
        max_output_tokens=max_output_tokens,
    )


def parse_response(output: str, game: Game) -> Extraction:
    try:
        extraction = Extraction.model_validate_json(output, strict=True)
        allowed = GAME_ENTRY_TYPES[game]
        if any(entry.type not in allowed for entry in extraction.entries) or any(
            cancellation.target_type not in allowed for cancellation in extraction.cancellations
        ):
            raise ExtractionError("invalid_game_entry_type", [
                {"loc": ["entries", index, "type"], "type": "invalid_game_entry_type"}
                for index, entry in enumerate(extraction.entries) if entry.type not in allowed
            ] + [
                {"loc": ["cancellations", index, "target_type"], "type": "invalid_game_entry_type"}
                for index, cancellation in enumerate(extraction.cancellations) if cancellation.target_type not in allowed
            ])
        extraction.entries = [
            entry for entry in extraction.entries
            if entry.type not in SONG_TYPES or any(song.strip() for song in entry.songs)
        ]
        extraction.entries, notes = merge_collab_contents(extraction.entries)
        extraction.notes += notes
        return extraction
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_input=False, include_context=False, include_url=False):
            # 未知のキー自体にも任意の文字列が入るため、保存する位置をスキーマのフィールドに限定する。
            loc = [part if isinstance(part, int) or part in {
                "entries", "cancellations", "notes", "review_notes", *Entry.model_fields, *Cancellation.model_fields
            } else "unknown_field" for part in error["loc"]]
            details.append({"loc": loc, "type": error["type"]})
        raise ExtractionError("invalid_structured_output", details) from exc


def collab_key(subject: str | None) -> tuple[str, str | None] | None:
    """対象名を作品名と弾数に分ける。弾数の表記がなければ弾数はNone。"""
    key = subject_key(subject)
    match = GENERATION.search(key or "")
    if not key or not match:
        return (key, None) if key else None
    number = next((group for group in match.groups() if group), None)
    work = key[:match.start()]
    return (work, number.translate(KANJI_DIGITS) if number else None) if work else None


def merge_collab_contents(entries: list[Entry]) -> tuple[list[Entry], list[str]]:
    """同じ作品・期間のイベントと別に出力されたマップ・ちほー・チャプターを、プロンプトの統合ルールどおりイベントにまとめる。

    作品名が一致し、開始日が同じで、終了日が同じかどちらかが未定のときだけ統合する。
    弾数は両方にあれば一致を必須とし、一致するイベントを優先する（第2弾のちほーをリバイバルではなく第2弾のコラボへ）。
    統合で消えるエントリの開始時刻・終了日時は、残るエントリで未定のときだけ引き継ぐ。
    """
    def compatible(first: object, second: object) -> bool:
        return first is None or second is None or first == second

    entries = list(entries)
    merged: set[int] = set()
    notes = []
    for index, content in enumerate(entries):
        key = collab_key(content.subject)
        if content.type not in CONTENT_TYPES or key is None:
            continue
        candidates = []
        for event_index, event in enumerate(entries):
            event_key = collab_key(event.subject)
            if (event.type == "event" and event_index not in merged and event_key and event_key[0] == key[0]
                    and compatible(event_key[1], key[1])
                    and event.start == content.start and compatible(event.end, content.end)):
                candidates.append((event_key[1] != key[1], event_index))
        if not candidates:
            continue
        event_index = min(candidates)[1]
        event = entries[event_index]
        # イベントの対象名がちほー名そのものなら、コラボではないちほーをイベントと誤分類したものとしてちほー側を残す。
        if CHIHO_NAME.search(subject_key(event.subject) or ""):
            kept_index, absorbed_index = index, event_index
        else:
            kept_index, absorbed_index = event_index, index
        kept, absorbed = entries[kept_index], entries[absorbed_index]
        update = {}
        if kept.start_time is None and absorbed.start_time is not None:
            update["start_time"] = absorbed.start_time
        if kept.end is None and absorbed.end is not None:
            update |= {"end": absorbed.end, "end_time": absorbed.end_time, "open_ended": False}
        elif kept.end_time is None and absorbed.end_time is not None and kept.end == absorbed.end:
            update["end_time"] = absorbed.end_time
        entries[kept_index] = kept.model_copy(update=update)
        merged.add(absorbed_index)
        notes.append(f"{absorbed.type}「{absorbed.subject}」は同じ作品・期間の{kept.type}「{kept.subject}」へ自動で統合しました。")
    return [entry for index, entry in enumerate(entries) if index not in merged], notes


def quote_key(text: str) -> str:
    return QUOTE_NOISE.sub("", unicodedata.normalize("NFKC", text))


def review_reasons(article: Article, extraction: Extraction) -> list[str]:
    reasons = list(extraction.review_notes)
    sources = [quote_key(source) for source in (article.title, article.body_text, article.body_markdown)]

    def quoted(text: str) -> bool:
        key = quote_key(text)
        return bool(key) and any(key in source for source in sources)

    if not article.body_text.strip() and not article.body_markdown.strip():
        reasons.append("本文がありません。タイトルのみの抽出です。")
    if article.date is None:
        reasons.append("記事の公開日が不明です。年の補完根拠を確認してください。")
    for index, entry in enumerate(extraction.entries, 1):
        prefix = f"エントリ{index}: "
        for field in ("date_text", "evidence"):
            quote = getattr(entry, field)
            if not quoted(quote):
                reasons.append(prefix + f"{field}の原文根拠を確認できません。")
        if entry.start is None:
            reasons.append(prefix + "開始日が不明です。")
        if entry.start and entry.end and entry.start > entry.end:
            reasons.append(prefix + "終了日が開始日より前です。")
        if (entry.start == entry.end and entry.start_time and entry.end_time
                and entry.start_time > entry.end_time):
            reasons.append(prefix + "終了時刻が開始時刻より前です。")
        if entry.open_ended and entry.end is not None:
            reasons.append(prefix + "終了日とopen_endedが矛盾しています。")
        if (entry.start_time and entry.start is None) or (entry.end_time and entry.end is None):
            reasons.append(prefix + "時刻に対応する日付がありません。")
        if entry.start_is_deadline and (entry.end is not None or entry.open_ended or entry.type == "maintenance"):
            reasons.append(prefix + "単日の期限と期間・メンテナンスの指定が矛盾しています。")
        if entry.service is None:
            reasons.append(prefix + "対象サービスが不明です。日付補正は行いません。")
        elif entry.service not in (article.game, "card_maker"):
            reasons.append(prefix + "対象サービスと記事のゲーム分類が一致しません。")
        maintenance = maintenance_for(entry, article.game)
        if maintenance and entry.type != "maintenance" and entry.start and entry.end and entry.end_time and not entry.open_ended:
            dates = calendar_dates(entry, article.game)
            if entry.end_time <= maintenance.start and dates["calendar_end"] == entry.end.isoformat():
                reasons.append(prefix + "前日補正すると終了日が開始日より前になります。")
        if entry.type in SONG_TYPES and (entry.end is not None or entry.end_time is not None):
            reasons.append(prefix + "楽曲・譜面追加に終了日があります。イベントやちほーの期間の流用でないか確認してください。")
        if entry.type == "other":
            reasons.append(prefix + "種類がotherです。")
        if entry.confidence < 0.8:
            reasons.append(prefix + "confidenceが0.8未満です。")
    for index, cancellation in enumerate(extraction.cancellations, 1):
        prefix = f"取り消し{index}: "
        if not quoted(cancellation.evidence):
            reasons.append(prefix + "evidenceの原文根拠を確認できません。")
        if cancellation.target_type == "other":
            reasons.append(prefix + "取り消し対象の種類が不明です。")
        if cancellation.confidence < 0.8:
            reasons.append(prefix + "confidenceが0.8未満です。")
        reasons.append(prefix + "元エントリとの照合が必要です。")
    return list(dict.fromkeys(reasons))


def content_hash(article: Article) -> str:
    source = article.model_dump(mode="json")
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def extract_article(client: JSONGenerator, article: Article, max_output_tokens: int) -> dict[str, Any]:
    source = article.model_dump(mode="json")
    result = {
        "source": {"game": source["game"], "url": source["url"], "date": source["date"], "title": source["title"]},
        "content_hash": content_hash(article),
        "entries": [], "cancellations": [], "notes": [], "review_reasons": [], "error": None,
        "validation_errors": [], "attempts": 0, "prompt_version": PROMPT_VERSION,
    }
    try:
        request = build_request(article, max_output_tokens)
        for attempt in range(MAX_EXTRACTION_ATTEMPTS):
            result["attempts"] = attempt + 1
            response = client.generate_json(request)
            try:
                extraction = parse_response(response, article.game)
                break
            except ExtractionError as exc:
                result["validation_errors"].append({"attempt": attempt + 1, "errors": exc.details})
                if attempt + 1 == MAX_EXTRACTION_ATTEMPTS:
                    raise
                request = replace(request, input=json.dumps({
                    "article": source,
                    "validation_errors": exc.details,
                }, ensure_ascii=False), instructions=build_request(article, max_output_tokens).instructions +
                    "\n前回の出力が検証に失敗しました。validation_errorsはプログラムの検証結果です。"
                    "指摘された項目を修正し、記事から全体を再抽出してください。"
                    "必須フィールドは省略せず、不明な値はスキーマで許可されたnullまたは空配列を使用してください。"
                    "不正な日付や種類を推測で置き換えず、記事に基づいて判断してください。")

        reasons = review_reasons(article, extraction)
        result.update(status="needs_review" if reasons else "extracted",
                      entries=[{"title": display_title(entry)} | entry.model_dump(mode="json") | calendar_dates(entry, article.game)
                               for entry in extraction.entries],
                      cancellations=[{"title": display_title(item)} | item.model_dump(mode="json")
                                     for item in extraction.cancellations],
                      notes=extraction.notes, review_reasons=reasons)
    except (ExtractionError, LLMError) as exc:
        result.update(status="failed", error=str(exc))
    return result


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_articles(path: Path) -> list[Article]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list):
        raise ValueError("入力JSONはスクレイパーが出力する記事の配列にしてください。")
    return [Article.model_validate(item) for item in raw]


def load_previous(path: Path) -> dict[str, dict[str, Any]]:
    """前回の抽出結果を記事URLで引けるようにする。ファイルがなければ空。

    版6の結果は記事ごとのプロバイダー・モデルを持たないため、文書全体の値を引き継ぐ。
    """
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(raw, dict) or raw.get("schema_version") not in READABLE_SCHEMA_VERSIONS
            or raw.get("mode") != "extraction" or not isinstance(raw.get("articles"), list)):
        raise ValueError("抽出結果のJSONではありません。")
    previous = {}
    for item in raw["articles"]:
        item.setdefault("provider", raw.get("provider"))
        item.setdefault("model", raw.get("model"))
        previous[item["source"]["url"]] = item
    return previous


def extraction_reason(article: Article, previous: dict[str, Any] | None, config: LLMConfig) -> str | None:
    """記事を抽出し直す理由。前回の結果をそのまま使えるならNone。"""
    if previous is None:
        return "new"
    if previous.get("content_hash") != content_hash(article):
        return "changed"
    if previous.get("prompt_version") != PROMPT_VERSION:
        return "prompt"
    if (previous.get("provider"), previous.get("model")) != (config.provider, config.model):
        return "model"
    if previous.get("status") == "failed":
        return "failed"
    return None


def entry_changes(before: dict[str, Any] | None, after: dict[str, Any]) -> list[str]:
    """記事のエントリの増減を、タイトルとカレンダー上の期間で表す。"""
    def keys(result: dict[str, Any] | None) -> Counter[str]:
        return Counter(
            " ".join(filter(None, [entry["title"], "〜".join(filter(None, [
                entry.get("calendar_start") or "日付不明", entry.get("calendar_end")]))]))
            for entry in (result or {}).get("entries", [])
        )
    old, new = keys(before), keys(after)
    return [f"  - {key}" for key in (old - new).elements()] + [f"  + {key}" for key in (new - old).elements()]


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env", override=False, encoding="utf-8-sig")
    parser = argparse.ArgumentParser(
        description="収集済みニュースをLLMでエントリに分解する。前回の結果から変わった記事だけを抽出する")
    parser.add_argument("--full", action="store_true", help="前回の結果を再利用せず、全記事を抽出し直す")
    parser.add_argument("--url", action="append", default=[], metavar="URL",
                        help="指定した記事を抽出し直す。複数回指定できる")
    parser.add_argument("--dry-run", action="store_true", help="抽出対象と理由を表示する。LLMを呼ばず、保存もしない")
    args = parser.parse_args(argv)
    source = Path("news_all.json")
    output = Path("entries.json")
    try:
        config = LLMConfig.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    try:
        articles = load_articles(source)
    except (OSError, ValueError) as exc:
        print(f"error: 入力JSONを読み込めません ({type(exc).__name__})", file=sys.stderr)
        return 2
    urls = [article.url for article in articles]
    unknown = [url for url in args.url if url not in urls]
    if unknown:
        parser.error("--urlの記事が入力JSONにありません: " + ", ".join(unknown))
    try:
        previous = load_previous(output)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"error: 既存の出力JSONを読み込めません ({type(exc).__name__})。"
              "移動または削除してから再実行してください。", file=sys.stderr)
        return 2

    targets = []
    for article in articles:
        reason = ("forced" if args.full or article.url in args.url
                  else extraction_reason(article, previous.get(article.url), config))
        if reason:
            targets.append((article, reason))
    if args.dry_run:
        for article, reason in targets:
            print(f"{reason}: [{article.game}] {article.date or '-'} {article.title} {article.url}")
        print(f"dry run: extract={len(targets)}, reuse={len(articles) - len(targets)}")
        return 0

    # 出力は入力記事の順。入力にない前回の記事も消さずに末尾へ残す。
    order = urls + [url for url in previous if url not in set(urls)]
    results = dict(previous)
    document = {"schema_version": SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
                "provider": config.provider, "model": config.model, "mode": "extraction",
                "articles": []}

    def save() -> None:
        document["articles"] = [results[url] for url in order if url in results]
        write_json(output, document)

    failed = 0
    try:
        if targets:
            try:
                config.validate_credentials()
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        save()
        if targets:
            remaining = iter(targets)
            with LLMClient(config) as client:
                with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
                    pending = {}

                    def submit_next() -> None:
                        item = next(remaining, None)
                        if item is not None:
                            article, reason = item
                            future = executor.submit(extract_article, client, article, MAX_OUTPUT_TOKENS)
                            pending[future] = (article, reason)

                    for _ in range(min(CONCURRENCY, len(targets))):
                        submit_next()
                    try:
                        while pending:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            for future in done:
                                article, reason = pending.pop(future)
                                result = future.result() | {"provider": config.provider, "model": config.model}
                                before = previous.get(article.url)
                                status = result["status"]
                                if status == "failed":
                                    failed += 1
                                    status += f" ({result['error']})"
                                # 失敗しても、前回成功した結果があれば残す。次回の実行で再び抽出対象になる。
                                if result["status"] == "failed" and before and before["status"] != "failed":
                                    status += ", 前回の結果を残します"
                                else:
                                    results[article.url] = result
                                save()
                                print(f"[{article.game}] {article.url}: {status} [{reason}]", file=sys.stderr)
                                for line in entry_changes(before, results[article.url]):
                                    print(line, file=sys.stderr)
                            for _ in done:
                                submit_next()
                    finally:
                        for future in pending:
                            future.cancel()
    except OSError as exc:
        print(f"error: 出力JSONを保存できません ({type(exc).__name__})", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("中断しました。保存済みの記事結果は出力ファイルに残っています。", file=sys.stderr)
        return 130
    print(f"{len(articles)} articles -> {output} "
          f"(extracted={len(targets)}, reused={len(articles) - len(targets)}, failed={failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
