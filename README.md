# mg-update-calendar

セガ音ゲーお知らせサイト (CHUNITHM / maimai / オンゲキ / 海外版CHUNITHM) のスクレイピングツール。
記事発表日・タイトル・画像URL・本文 (プレーン + Markdown) をJSON化する。

## 環境構築（Windows / PowerShell）

前提：Git のみ。Python は `uv` が `.python-version`（3.12）を見て自動調達する。

```powershell
# 1. uv が無ければインストール
irm https://astral.sh/uv/install.ps1 | iex

# 2. リポジトリ取得
git clone <repo-url> mg-update-calendar
cd mg-update-calendar

# 3. 依存関係を同期（.venv 作成＋ beautifulsoup4 / requests 導入）
uv sync

# 4. 動作確認
uv run mg-update-calendar --help
```

上書き・復旧：

```powershell
# 依存が壊れたら .venv を消して入れ直し（.venv は git 管理外）
Remove-Item -Recurse -Force .venv
uv sync
```

## 起動コマンド

```powershell
# CHUNITHM（国内版、デフォルト）
uv run mg-update-calendar --game chunithm --max-pages 1 --output news.json

# maimai
uv run mg-update-calendar --game maimai --max-pages 1 --output news_maimai.json

# オンゲキ
uv run mg-update-calendar --game ongeki --max-pages 1 --output news_ongeki.json

# CHUNITHM International版（https://info-chunithm.sega.com/）
uv run mg-update-calendar --game chunithm_intl --max-pages 1 --output news_chunithm_intl.json

# 全4ゲームまとめて取得
uv run mg-update-calendar --game all --max-pages 1 --output news_all.json
```

## オプション

| オプション | 説明 | 既定値 |
| --- | --- | --- |
| `--game` | `chunithm` / `maimai` / `ongeki` / `chunithm_intl` / `all` | `chunithm` |
| `--max-pages` | ゲームごとの一覧ページ数 (`/page/N/`)。0以下は全ページ巡回 | `1` |
| `--max-articles` | ゲームごとの記事数上限。0=無制限 | `0` |
| `--output`, `-o` | 出力JSONパス。省略時は `news_<game>.json` (`all`時は `news_all.json`) | - |
| `--no-detail` | 記事詳細ページを取得せず一覧情報のみでJSON化（高速・低負荷） | - |
| `--interval` | リクエスト間隔（秒）。1秒未満は不可 | `1.0` |

例：

```powershell
# 一覧のみ高速取得、記事3件まで
uv run mg-update-calendar --game chunithm_intl --max-pages 1 --max-articles 3 --no-detail --output news_chunithm_intl.json

# ヘルプ
uv run mg-update-calendar --help
```

## 注意

- サーバ負荷軽減のため、リクエスト間隔は必ず1秒以上（ゲームまたぎでも維持）。
- 出力JSON (`*.json`) は `.gitignore` で除外され、Gitには上がらない。
