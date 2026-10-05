from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

from mg_update_calendar.extractor import CONCURRENCY, MAX_OUTPUT_TOKENS, extract_article, load_articles, write_json
from mg_update_calendar.llm import LLMClient, LLMConfig
from mg_update_calendar.models import Article
from mg_update_calendar.prompts import PROMPT_VERSION

DEFAULT_CASES = Path("tests/regression_cases.json")
# 期待値に書ける項目。songs_includeは、列挙した曲名がすべてsongsに含まれることを表す。
MATCH_FIELDS = frozenset({"type", "title", "subject", "label", "official_name", "service", "start", "start_time",
                          "end", "end_time", "open_ended", "start_is_deadline", "songs_include"})


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    for case in cases:
        patterns = case.get("expect", []) + case.get("forbid", [])
        unknown = {key for pattern in patterns for key in pattern} - MATCH_FIELDS
        if unknown:
            raise ValueError(f"{case['url']}: 期待値に使えない項目があります: {', '.join(sorted(unknown))}")
    urls = [case["url"] for case in cases]
    if len(urls) != len(set(urls)):
        raise ValueError("同じ記事のケースが重複しています。")
    return cases


def matches(entry: dict[str, Any], pattern: dict[str, Any]) -> bool:
    for key, value in pattern.items():
        if key == "songs_include":
            titles = {song["title"] for song in entry.get("songs", [])}
            if not set(value) <= titles:
                return False
        elif entry.get(key) != value:
            return False
    return True


def describe(pattern: dict[str, Any]) -> str:
    return ", ".join(f"{key}={value}" for key, value in pattern.items())


def evaluate(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """抽出結果がケースの期待値を満たさない点を返す。満たしていれば空。"""
    if result.get("status") == "failed":
        return [f"抽出に失敗しました: {result.get('error')}"]
    entries = result.get("entries", [])
    failures = []
    if "status" in case and result.get("status") != case["status"]:
        failures.append(f"状態が{case['status']}ではありません: {result.get('status')}")
    for pattern in case.get("expect", []):
        if not any(matches(entry, pattern) for entry in entries):
            failures.append(f"見つかりません: {describe(pattern)}")
    for pattern in case.get("forbid", []):
        found = [entry["title"] for entry in entries if matches(entry, pattern)]
        if found:
            failures.append(f"出てはいけないエントリがあります（{describe(pattern)}）: {', '.join(found)}")
    for kind, (low, high) in case.get("count", {}).items():
        count = sum(1 for entry in entries if entry["type"] == kind)
        if not low <= count <= high:
            failures.append(f"{kind}が{count}件です（{low}〜{high}件の想定）")
    return failures


def report(cases: list[dict[str, Any]], runs: dict[str, list[dict[str, Any]]]) -> int:
    """ケースごとの合格回数と失敗内容を表示し、すべて合格した回数のケース数を返す。"""
    passed = 0
    for case in cases:
        results = runs.get(case["url"], [])
        failures = [evaluate(case, result) for result in results]
        ok = sum(1 for items in failures if not items)
        passed += ok == len(results) and bool(results)
        mark = "OK  " if ok == len(results) and results else "NG  "
        print(f"{mark}{ok}/{len(results)} {case['url']} {case.get('reason', '')}")
        for message, times in Counter(item for items in failures for item in items).most_common():
            print(f"      {times}回: {message}")
    return passed


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env", override=False, encoding="utf-8-sig")
    parser = argparse.ArgumentParser(
        description="回帰テスト用の記事を抽出し、期待値と照合する。記事の本文はnews_all.jsonから読む")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="ケースのJSON")
    parser.add_argument("--from", dest="source", type=Path, metavar="ENTRIES_JSON",
                        help="LLMを呼ばず、既存の抽出結果を照合する")
    parser.add_argument("--case", action="append", default=[], metavar="TEXT",
                        help="URLにTEXTを含むケースだけを実行する。複数回指定できる")
    parser.add_argument("--repeat", type=int, default=1, help="抽出のゆれを見るため、各記事を抽出する回数")
    parser.add_argument("--output", type=Path, default=Path("regression_result.json"), help="抽出結果の保存先")
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeatは1以上にしてください。")
    try:
        cases = load_cases(args.cases)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: ケースを読み込めません ({exc})", file=sys.stderr)
        return 2
    if args.case:
        cases = [case for case in cases if any(text in case["url"] for text in args.case)]
        if not cases:
            parser.error("--caseに一致するケースがありません。")

    if args.source:
        raw = json.loads(args.source.read_text(encoding="utf-8-sig"))
        # 抽出結果（entries.json）と、この回帰テストの保存結果のどちらも照合できる。
        if "runs" in raw:
            runs = {case["url"]: raw["runs"][case["url"]] for case in cases if case["url"] in raw["runs"]}
        else:
            results = {item["source"]["url"]: item for item in raw["articles"]}
            runs = {case["url"]: [results[case["url"]]] for case in cases if case["url"] in results}
    else:
        articles: dict[str, Article] = {article.url: article for article in load_articles(Path("news_all.json"))}
        missing = [case["url"] for case in cases if case["url"] not in articles]
        if missing:
            print("error: news_all.jsonにない記事があります: " + ", ".join(missing), file=sys.stderr)
            return 2
        config = LLMConfig.from_env()
        try:
            config.validate_credentials()
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        jobs = [case["url"] for case in cases for _ in range(args.repeat)]
        with LLMClient(config) as client, ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            outputs = list(executor.map(lambda url: extract_article(client, articles[url], MAX_OUTPUT_TOKENS), jobs))
        runs = {}
        for url, output in zip(jobs, outputs):
            runs.setdefault(url, []).append(output)
        write_json(args.output, {"prompt_version": PROMPT_VERSION, "provider": config.provider, "model": config.model,
                                 "runs": runs})

    passed = report(cases, runs)
    print(f"{passed}/{len(cases)} cases passed (prompt_version={PROMPT_VERSION})")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
