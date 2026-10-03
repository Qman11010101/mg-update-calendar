"""セガ音ゲーおしらせサイト (CHUNITHM / maimai / オンゲキ / 海外版CHUNITHM) のスクレイピングスクリプト.

記事発表日・タイトル・画像URL・本文 (プレーン + Markdown) をJSON化する.

使い方 (uv 前提):
    uv run mg-update-calendar --game chunithm --max-pages 1 --output news.json
    uv run mg-update-calendar --game maimai --max-pages 2 --output news_maimai.json
    uv run mg-update-calendar --game all --max-pages 1 --output news_all.json

仕様:
- 一覧ページ (各サイトのトップ , /page/N/) から記事URLを取得
- 各記事ページを fetch して 発表日・タイトル・画像URL(og:image + 本文画像)を取得
- HTTPリクエストとリクエストの間には必ず1秒の間隔をあける (time.sleep(1))。
  複数ゲームを連続取得する場合もゲームをまたいで間隔を保つ。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify

# サーバ負荷軽減のためのウェイト (秒)。要件: 複数回スクレイピング時は必ず1秒あける
REQUEST_INTERVAL_SEC = 1.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; mg-update-calendar/0.1.0)",
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# "2026.09.15 (火)" (CHUNITHM/maimai) / "2026.9.15 Tue / GAME" (オンゲキ) / "2026.9.16Wed" (海外版CHUNITHM) に対応
DATE_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")


@dataclass(frozen=True)
class SiteConfig:
    """ゲームごとのサイト差分。セレクタ以外のパース logic は共通。"""

    game: str  # 出力JSONの game フィールド ("chunithm" | "maimai" | "ongeki" | "chunithm_intl")
    label: str  # 表示名
    base_url: str
    page_url_template: str
    # 一覧ページ
    card_selector: str  # 記事カードへのリンク
    list_date_selector: str
    list_title_selector: str
    list_thumb_selector: str
    # 一覧タイトル要素内で除去すべき子要素 (CHUNITHMのみ。サムネイルdivとNEW!!バッジ)
    list_title_cleanup: tuple[str, ...] = ()
    # 詳細ページ
    detail_date_selector: str = ""
    detail_title_selector: str = ""
    detail_body_selector: str = ""
    # 日付テキストに " / カテゴリ" が付随するか (オンゲキのみ。site_category として分離)
    category_in_date: bool = False


SITES: dict[str, SiteConfig] = {
    "chunithm": SiteConfig(
        game="chunithm",
        label="CHUNITHM",
        base_url="https://info-chunithm.sega.jp/",
        page_url_template="https://info-chunithm.sega.jp/page/{page}/",
        card_selector=".newsMainWrapper-left > a[href]",
        list_date_selector=".chuniCommonBox-inner-title .title",
        list_title_selector=".chuniCommonBox-inner-main",
        list_thumb_selector=".newsList-thumbnail img",
        list_title_cleanup=(".newsList-thumbnail", ".NewIcon"),
        detail_date_selector=".chuniCommonBox-inner-date",
        detail_title_selector=".chuniCommonBox-inner-title .title",
        detail_body_selector=".chuniMd",
    ),
    "maimai": SiteConfig(
        game="maimai",
        label="maimai",
        base_url="https://info-maimai.sega.jp/",
        page_url_template="https://info-maimai.sega.jp/page/{page}/",
        card_selector=".newsBox a[href]",
        list_date_selector=".newsDate",
        list_title_selector=".newsLink",
        list_thumb_selector=".newsThumb img",
        detail_date_selector=".articleDate",
        detail_title_selector=".articleTitle",
        detail_body_selector=".maiMd",
    ),
    "ongeki": SiteConfig(
        game="ongeki",
        label="オンゲキ",
        base_url="https://info-ongeki.sega.jp/",
        page_url_template="https://info-ongeki.sega.jp/page/{page}/",
        card_selector="a.p-news__listLink[href]",
        list_date_selector=".p-news__listTextUpper",
        list_title_selector=".p-news__listTextUnder",
        list_thumb_selector=".p-news__listThumb img",
        detail_date_selector=".p-news__articleInfo",
        detail_title_selector=".p-news__articleTitle",
        detail_body_selector=".p-news__articleBodyInner",
        category_in_date=True,
    ),
    "chunithm_intl": SiteConfig(
        game="chunithm_intl",
        label="CHUNITHM International",
        base_url="https://info-chunithm.sega.com/",
        page_url_template="https://info-chunithm.sega.com/page/{page}/",
        card_selector="li.news--list__item a.news--list__post[href]",
        list_date_selector=".news--date",
        list_title_selector=".news--title",
        list_thumb_selector=".news--thumbnail img",
        detail_date_selector=".news--post__date",
        detail_title_selector=".news--post__ttl",
        detail_body_selector=".news--post__details--wrap",
    ),
}


def normalize_date(raw: str) -> str:
    """'2026.09.15 (火)' / '2026.9.15 Tue' -> '2026-09-15'。変換できなければ strip して返す。"""
    m = DATE_RE.search(raw or "")
    if not m:
        return (raw or "").strip()
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def split_date_category(text: str) -> tuple[str, str]:
    """オンゲキ式 '2026.9.15 Tue / GAME' -> ('2026.9.15 Tue', 'GAME')。"""
    if "/" in text:
        date_part, _, cat_part = text.partition("/")
        return date_part.strip(), cat_part.strip()
    return text.strip(), ""


def make_record(
    *,
    game: str,
    url: str,
    date_raw: str,
    title: str,
    image_url: str = "",
    image_urls: list[str] | None = None,
    redirect_url: str = "",
    site_category: str = "",
    body_text: str = "",
    body_markdown: str = "",
    headings: list[str] | None = None,
) -> dict:
    """出力レコード雛形。キーの順序・有無を全ゲームで統一する。"""
    return {
        "game": game,
        "url": url,
        "date_raw": date_raw,
        "date": normalize_date(date_raw),
        "title": title,
        "image_url": image_url,
        "image_urls": image_urls or [],
        "redirect_url": redirect_url,
        "site_category": site_category,
        "body_text": body_text,
        "body_markdown": body_markdown,
        "headings": headings or [],
    }


def fetch_html(session: requests.Session, url: str, timeout: int = 15) -> str:
    """1件のHTTP GET。呼び出し側で1秒間隔を担保すること。"""
    resp = session.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    # WordPressサイトは charset=utf-8 を返すが、念のため apparent_encoding にフォールバック
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


class Fetcher:
    """1秒間隔を担保する共有GET窓口。複数ゲーム連続取得でも間隔を保つ。"""

    def __init__(self, interval: float = REQUEST_INTERVAL_SEC, verbose: bool = True) -> None:
        self.session = requests.Session()
        self.interval = interval
        self.verbose = verbose
        self._first = True

    def get(self, url: str) -> str:
        # 要件: スクレイピングを複数行うときは必ず1秒の間隔をあける
        if not self._first:
            time.sleep(self.interval)
        self._first = False
        if self.verbose:
            print(f"fetch: {url}", file=sys.stderr)
        return fetch_html(self.session, url)


def parse_list_page(html: str, site: SiteConfig) -> list[dict]:
    """一覧ページHTMLから記事カードを抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(site.base_url).netloc
    articles: list[dict] = []

    for a in soup.select(site.card_selector):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        url = urljoin(site.base_url, href)
        # 自サイトの記事URLのみ。ページネーション (/page/N/) とカテゴリ (/category/) を除外
        if urlparse(url).netloc != host:
            continue
        if "/page/" in url or "/category/" in url:
            continue

        date_el = a.select_one(site.list_date_selector)
        date_raw = date_el.get_text(strip=True) if date_el else ""
        site_category = ""
        if site.category_in_date:
            date_raw, site_category = split_date_category(date_raw)

        img_el = a.select_one(site.list_thumb_selector)
        thumb_url = ""
        thumb_alt = ""
        if img_el:
            thumb_url = (img_el.get("src") or "").strip()
            thumb_alt = (img_el.get("alt") or "").strip()
            if thumb_url:
                thumb_url = urljoin(site.base_url, thumb_url)

        title = ""
        title_el = a.select_one(site.list_title_selector)
        if title_el is not None:
            for unwanted_sel in site.list_title_cleanup:
                for unwanted in title_el.select(unwanted_sel):
                    unwanted.decompose()
            title = title_el.get_text(separator=" ", strip=True)
        # フォールバック: サムネイルimgのalt属性 (alt=タイトルになっていることが多い)
        if not title:
            title = thumb_alt

        if not title:
            continue

        articles.append(
            make_record(
                game=site.game,
                url=url,
                date_raw=date_raw,
                title=title,
                image_url=thumb_url,
                image_urls=[thumb_url] if thumb_url else [],
                site_category=site_category,
            )
        )
    return articles


def parse_article_page(html: str, url: str, site: SiteConfig) -> dict:
    """記事詳細ページHTMLから発表日・タイトル・画像URL・本文を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")

    date_el = soup.select_one(site.detail_date_selector)
    title_el = soup.select_one(site.detail_title_selector)
    date_raw = date_el.get_text(strip=True) if date_el else ""
    title = title_el.get_text(strip=True) if title_el else ""
    site_category = ""
    if site.category_in_date:
        date_raw, site_category = split_date_category(date_raw)

    # フォールバック: og:title
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

    # メイン画像は og:image を優先 (一覧サムネイルと同一のことが多い)
    image_url = ""
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        image_url = urljoin(url, og_image["content"].strip())

    # 本文中の全画像も収集
    image_urls: list[str] = []
    body_el = soup.select_one(site.detail_body_selector) if site.detail_body_selector else None
    if body_el is not None:
        for img in body_el.select("img[src]"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            abs_url = urljoin(url, src)
            if abs_url not in image_urls:
                image_urls.append(abs_url)

    # og:image が本文画像に無ければ先頭に挿入
    if image_url and image_url not in image_urls:
        image_urls.insert(0, image_url)
    # og:image が無い場合は本文先頭画像を代表にする
    if not image_url and image_urls:
        image_url = image_urls[0]

    # JSリダイレクト記事の検出。
    # 例: おサイフケータイ記事の本文は実コンテンツを持たず、
    #   <p><script>location.href="https://my-aime.net/news/detail?newsId=290";</script></p>
    # のみ。ブラウザでは即座に外部サイトへ遷移するが、requestsはJSを実行しないため
    # HTTPレベルでは200のまま・リダイレクト履歴なしで取得できる。
    # 遷移先URLを redirect_url として記録する (通常記事は "")。
    redirect_url = ""
    body_scope = body_el if body_el is not None else soup
    for script in body_scope.select("script"):
        script_text = script.get_text() or ""
        m = re.search(
            r"location\.(?:href\s*=\s*|replace\s*\(\s*)[\"']([^\"']+)[\"']",
            script_text,
        )
        if m:
            redirect_url = urljoin(url, m.group(1).strip())
            break

    # 本文テキスト・見出し・Markdownを抽出する。
    # - カレンダー化に必須: イベント期間 (終了日)・楽曲名などの「内容」は
    #   タイトルだけでは取れず、本文にしか書かれていないため。
    #   例: "2026年9月17日(木)～2026年10月21日(水)までの期間で" (CHUNITHMコラボ)、
    #       "9/17(木)～9/30(水)23:59の期間で" (オンゲキランキングイベ)、
    #       "新曲「Yami Yami」...を追加" (楽曲名)。
    # - script/style は本文テキストから除外する (リダイレクト用JS等が混ざるため)。
    # - 2形式を併存させる理由:
    #   body_text (プレーン) は日付正規表現用。Markdown化すると画像・リンクのURL
    #   (例: ".../img/6/09/poster.png" 中の "6/09") が日付に誤検出され得るため、
    #   アルゴリズムにはURLを含まないプレーン文本を使い続ける。
    #   body_markdown は表・見出し・リストの構造を保ったAI/人間向け。本文の主役はこちら。
    headings: list[str] = []
    body_text = ""
    body_markdown = ""
    if body_el is not None:
        for a in body_el.select("a[href]"):
            href = (a.get("href") or "").strip()
            if href:
                a["href"] = urljoin(url, href)
        for img in body_el.select("img[src]"):
            src = (img.get("src") or "").strip()
            if src:
                img["src"] = urljoin(url, src)
        for tag in body_el.select("script, style"):
            tag.decompose()
        headings = [
            h.get_text(separator=" ", strip=True)
            for h in body_el.select("h1, h2, h3, h4")
        ]
        headings = [h for h in headings if h]
        raw_text = body_el.get_text(separator="\n", strip=True)
        # 空行の肥大化を抑える (3連続改行→2連続に)
        body_text = re.sub(r"\n{3,}", "\n\n", raw_text).strip()
        body_markdown = markdownify(
            str(body_el),
            heading_style="ATX",
            # オンゲキの楽曲・報酬表は <th> 無しが多いので先頭行を見出し扱いにする
            table_infer_header=True,
        )
        body_markdown = re.sub(r"\n{3,}", "\n\n", body_markdown).strip()

    return make_record(
        game=site.game,
        url=url,
        date_raw=date_raw,
        title=title,
        image_url=image_url,
        image_urls=image_urls,
        redirect_url=redirect_url,
        site_category=site_category,
        body_text=body_text,
        body_markdown=body_markdown,
        headings=headings,
    )


def scrape(
    max_pages: int = 1,
    max_articles: int = 0,
    fetch_detail: bool = True,
    interval: float = REQUEST_INTERVAL_SEC,
    verbose: bool = True,
    game: str = "chunithm",
    fetcher: Fetcher | None = None,
) -> list[dict]:
    """一覧+詳細をスクレイピングしてJSON化可能なlist[dict]を返す。

    Args:
        max_pages: 取得する一覧ページ数 (1 = トップのみ)。0以下は全ページ巡回。
        max_articles: 取得する記事数の上限。0 = 上限なし。
        fetch_detail: Trueなら各記事ページも取得して正確な日付/画像を得る。
        interval: リクエスト間隔(秒)。要件によりデフォルト1.0秒。
        verbose: 進捗をstderrに出す。
        game: 対象ゲーム ("chunithm" | "maimai" | "ongeki" | "chunithm_intl")。
        fetcher: 共有Fetcher。複数ゲーム連続取得時に渡すとゲームまたぎの間隔も保つ。
    """
    site = SITES[game]
    if fetcher is None:
        fetcher = Fetcher(interval=interval, verbose=verbose)
    results: list[dict] = []
    seen_urls: set[str] = set()

    page = 1
    while True:
        if max_pages > 0 and page > max_pages:
            break
        list_url = site.base_url if page == 1 else site.page_url_template.format(page=page)
        try:
            html = fetcher.get(list_url)
        except requests.HTTPError as e:
            # 存在しないページ番号 (404) なら巡回終了
            if e.response is not None and e.response.status_code == 404:
                if verbose:
                    print(f"[{site.game}] page {page} is 404, stop.", file=sys.stderr)
                break
            raise

        cards = parse_list_page(html, site)
        if not cards:
            if verbose:
                print(f"[{site.game}] page {page}: no articles, stop.", file=sys.stderr)
            break

        for card in cards:
            if card["url"] in seen_urls:
                continue
            seen_urls.add(card["url"])

            if fetch_detail:
                try:
                    detail_html = fetcher.get(card["url"])
                except requests.HTTPError as e:
                    if verbose:
                        print(f"warn: failed {card['url']}: {e}", file=sys.stderr)
                    # 詳細取得に失敗したら一覧情報でフォールバック
                    results.append(card)
                    if max_articles > 0 and len(results) >= max_articles:
                        return results
                    continue
                detail = parse_article_page(detail_html, card["url"], site)
                # 詳細ページで取れなかった項目は一覧情報で補完
                if not detail["title"]:
                    detail["title"] = card["title"]
                if not detail["date_raw"]:
                    detail["date_raw"] = card["date_raw"]
                    detail["date"] = card["date"]
                if not detail["site_category"]:
                    detail["site_category"] = card["site_category"]
                if not detail["image_url"]:
                    detail["image_url"] = card["image_url"]
                for thumb in reversed(card["image_urls"]):
                    if thumb and thumb not in detail["image_urls"]:
                        detail["image_urls"].insert(0, thumb)
                results.append(detail)
            else:
                results.append(card)

            if max_articles > 0 and len(results) >= max_articles:
                return results

        page += 1

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="セガ音ゲーおしらせ (CHUNITHM/maimai/オンゲキ/海外版CHUNITHM) をスクレイピングしてJSON化する"
    )
    parser.add_argument(
        "--game",
        choices=["chunithm", "maimai", "ongeki", "chunithm_intl", "all"],
        default="chunithm",
        help="対象ゲーム。allで4ゲームまとめて取得 (default: chunithm)",
    )
    parser.add_argument("--max-pages", type=int, default=1, help="ゲームごとの一覧ページ数 (default: 1)")
    parser.add_argument("--max-articles", type=int, default=0, help="ゲームごとの記事数上限。0=無制限 (default: 0)")
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="出力JSONファイルパス。省略時は news_<game>.json (all時は news_all.json)",
    )
    parser.add_argument(
        "--no-detail",
        action="store_true",
        help="記事詳細ページを取得せず一覧情報のみでJSON化する (高速・低負荷)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=REQUEST_INTERVAL_SEC,
        help="リクエスト間隔(秒)。1秒未満は許可しない (default: 1.0)",
    )
    args = parser.parse_args(argv)

    if args.interval < 1.0:
        print("error: --interval は1秒以上を指定してください (サーバ負荷軽減のため)", file=sys.stderr)
        return 2

    games = list(SITES) if args.game == "all" else [args.game]
    output = args.output or (f"news_{args.game}.json")

    # Fetcherを共有し、ゲームまたぎでも1秒間隔を保つ
    fetcher = Fetcher(interval=args.interval, verbose=True)
    all_articles: list[dict] = []
    for game in games:
        articles = scrape(
            max_pages=args.max_pages,
            max_articles=args.max_articles,
            fetch_detail=not args.no_detail,
            interval=args.interval,
            game=game,
            fetcher=fetcher,
        )
        print(f"[{game}] {len(articles)} articles", file=sys.stderr)
        all_articles.extend(articles)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"{len(all_articles)} articles -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
