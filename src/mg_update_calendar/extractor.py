from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from mg_update_calendar.models import Article, Extraction, Game, GAME_ENTRY_TYPES, ENTRY_LABELS, extraction_schema
from mg_update_calendar.llm import JSONGenerator, LLMClient, LLMConfig, LLMError, LLMRequest
from mg_update_calendar.prompts import PROMPT_VERSION, SYSTEM_PROMPT
from mg_update_calendar.event_identity import event_id
from mg_update_calendar.services import SERVICE_MAINTENANCE, calendar_dates, maintenance_for

MAX_OUTPUT_TOKENS = 8192
CONCURRENCY = 5
SONG_REQUIRED_TYPES = frozenset({
    "song_add", "song_unlock", "ultima_add", "worlds_end_add", "remaster_add",
    "dx_chart_add", "standard_chart_add", "utage_add", "lunatic_add",
})


class ExtractionError(Exception):
    pass


def build_request(article: Article, max_output_tokens: int) -> LLMRequest:
    services = (article.game, "card_maker") if article.game != "chunithm_intl" else (article.game,)
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
            raise ExtractionError("invalid_game_entry_type")
        extraction.entries = [
            entry for entry in extraction.entries
            if entry.type not in SONG_REQUIRED_TYPES or any(song.strip() for song in entry.songs)
        ]
        return extraction
    except ValidationError as exc:
        raise ExtractionError("invalid_structured_output") from exc


def review_reasons(article: Article, extraction: Extraction) -> list[str]:
    reasons = list(extraction.review_notes)
    sources = (article.title, article.body_text, article.body_markdown)
    if not article.body_text.strip() and not article.body_markdown.strip():
        reasons.append("本文がありません。タイトルのみの抽出です。")
    if article.date is None:
        reasons.append("記事の公開日が不明です。年の補完根拠を確認してください。")
    if article.game == "chunithm_intl":
        reasons.append("海外版のタイムゾーンおよび画像内の情報は未確認です。")
    for index, entry in enumerate(extraction.entries, 1):
        prefix = f"エントリ{index}: "
        for field in ("date_text", "evidence"):
            quote = getattr(entry, field)
            if not quote or not any(quote in source for source in sources):
                reasons.append(prefix + f"{field}の原文根拠を確認できません。")
        if entry.event_name is not None and event_id(entry, article) is None:
            reasons.append(prefix + "所属イベントの原文根拠・対象サービス・開催期間・確信度を確認できません。自動グループ化しません。")
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
        if entry.type == "other":
            reasons.append(prefix + "種類がotherです。")
        if entry.confidence < 0.8:
            reasons.append(prefix + "confidenceが0.8未満です。")
    for index, cancellation in enumerate(extraction.cancellations, 1):
        prefix = f"取り消し{index}: "
        if not any(cancellation.evidence in source for source in sources):
            reasons.append(prefix + "evidenceの原文根拠を確認できません。")
        if cancellation.target_type == "other":
            reasons.append(prefix + "取り消し対象の種類が不明です。")
        if cancellation.confidence < 0.8:
            reasons.append(prefix + "confidenceが0.8未満です。")
        reasons.append(prefix + "元エントリとの照合が必要です。")
    return list(dict.fromkeys(reasons))


def extract_article(client: JSONGenerator, article: Article, max_output_tokens: int) -> dict[str, Any]:
    source = article.model_dump(mode="json")
    result = {
        "source": {"game": source["game"], "url": source["url"], "date": source["date"], "title": source["title"]},
        "content_hash": hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "entries": [], "cancellations": [], "review_reasons": [], "error": None,
    }
    try:
        response = client.generate_json(build_request(article, max_output_tokens))
        extraction = parse_response(response, article.game)
        reasons = review_reasons(article, extraction)
        result.update(status="needs_review" if reasons else "extracted",
                      entries=[entry.model_dump(mode="json") | calendar_dates(entry, article.game) | {"event_id": event_id(entry, article)} for entry in extraction.entries],
                      cancellations=extraction.model_dump(mode="json")["cancellations"], review_reasons=reasons)
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


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env", override=False, encoding="utf-8-sig")
    parser = argparse.ArgumentParser(description="収集済みニュースをLLMでエントリに分解する")
    parser.parse_args(argv)
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
    document = {"schema_version": 4, "prompt_version": PROMPT_VERSION,
                "provider": config.provider, "model": config.model, "mode": "extraction", "articles": []}
    try:
        if articles:
            try:
                config.validate_credentials()
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        write_json(output, document)
        if articles:
            completed = {}
            remaining = iter(enumerate(articles))
            with LLMClient(config) as client:
                with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
                    pending = {}

                    def submit_next() -> None:
                        item = next(remaining, None)
                        if item is not None:
                            index, article = item
                            future = executor.submit(extract_article, client, article, MAX_OUTPUT_TOKENS)
                            pending[future] = (index, article)

                    for _ in range(min(CONCURRENCY, len(articles))):
                        submit_next()
                    try:
                        while pending:
                            done, _ = wait(pending, return_when=FIRST_COMPLETED)
                            for future in done:
                                index, article = pending.pop(future)
                                result = future.result()
                                completed[index] = result
                                document["articles"] = [completed[i] for i in sorted(completed)]
                                write_json(output, document)
                                print(f"[{article.game}] {article.url}: {result['status']}", file=sys.stderr)
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
    failed = sum(item["status"] == "failed" for item in document["articles"])
    print(f"{len(articles)} articles -> {output} ({document['mode']}, failed={failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
