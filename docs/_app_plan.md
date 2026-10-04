# Cloudflare Workers 移行計画（下書き）

> ざっくり下書き。数値・制限値・料金は着手時にCloudflare公式ドキュメントで再確認すること。

## 目的

- 手元で `mg-update-calendar` → `mg-extract-entries` → `Copy-Item` → push している運用を自動化する
- 抽出結果を `docs/entries.json` 一枚ではなくDB（D1）で管理し、差分更新・履歴・手動修正をできるようにする
- カレンダーをCloudflare Workers上で公開し、API経由でデータを返す

## 現状の整理

| 段階 | 現在の実装 | 入出力 |
| --- | --- | --- |
| 記事収集 | Python（requests + BeautifulSoup + markdownify） | 公式サイト → `news_all.json` |
| 告知抽出 | Python（openai SDK + Pydantic、OpenAI / DeepSeek） | `news_all.json` → `entries.json` |
| 表示時の重複統合 | JavaScript（`calendar.js`） | 内容・日時等が完全一致する項目の出典を保持 |
| 表示 | 静的HTML/JS（`docs/`）、GitHub Pagesで公開 | `docs/entries.json` を読む |

課題:

- 毎回全記事を再抽出している（`content_hash` はあるが再利用していない）
- 記事をまたぐ取り消し・延期の適用が手動確認頼み
- `needs_review` の確認・修正を記録する場所がない

## 方針（案）

**段階的に移行する。** いきなり全部をWorkersに載せず、まずDBと表示をWorkersに寄せ、収集・抽出は後から移す。

### 収集・抽出をどこで動かすか

| 案 | 内容 | 長所 | 短所 |
| --- | --- | --- | --- |
| A. Pythonのまま外部実行 | GitHub Actionsのスケジュール実行で現行コードを動かし、結果をWorkersのAPI（またはD1 HTTP API / `wrangler d1 execute`）に書き込む | 既存コードとテストをそのまま使える | 実行基盤が2つに分かれる |
| B. Python Workers | 現行コードをPython Workersに移植 | 言語を変えずに済む | requests / BeautifulSoup / openai SDK がそのまま動く保証がない。要検証 |
| C. TypeScriptで書き直し | Workers + Cron Triggers + Queues で収集・抽出 | Cloudflare内で完結、Queuesで1記事ずつ再試行しやすい | 書き直しコストが大きい。Pydantic相当（Zodなど）も移植が必要 |

→ **フェーズ1〜2はA、安定したらCを検討**。Bは小さく試してみて動くなら候補に入れる。

## 構成イメージ（最終形）

```
Cron Trigger (例: 1日数回)
  └─ 収集Worker: 一覧ページ取得 → 新規/更新記事を判定 → D1 articles に保存
       └─ Queue: 抽出が必要な記事IDを投入
            └─ 抽出Worker(consumer): LLM API呼び出し → 検証 → D1 entries に保存
                 └─ 重複照合・取り消し照合
公開Worker
  ├─ Static Assets: index.html / calendar.js / style.css
  ├─ GET /api/entries?from=&to=&game=  … カレンダー表示用
  └─ /admin/*  … needs_review の確認・修正（Cloudflare Accessで保護）
```

- APIキー（OpenAI / DeepSeek）は Workers Secrets に置く
- 記事本文のHTML・LLMの生レスポンスなど大きいものは必要なら R2 に置き、D1にはキーだけ持つ
- 表示用APIはCache API / KVで短時間キャッシュしてもよい（D1の読み取りが少ないなら不要）

## D1 スキーマ案

叩き台。`entries.json` の `schema_version: 5` の構造をほぼそのまま正規化する。

```sql
-- 収集した記事
CREATE TABLE articles (
  id            INTEGER PRIMARY KEY,
  game          TEXT NOT NULL,              -- chunithm / maimai / ongeki
  url           TEXT NOT NULL UNIQUE,
  published_on  TEXT NOT NULL,              -- YYYY-MM-DD
  title         TEXT NOT NULL,
  image_url     TEXT,
  body_text     TEXT,
  body_markdown TEXT,
  content_hash  TEXT NOT NULL,              -- 再抽出要否の判定に使う
  fetched_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

-- 記事ごとの抽出実行（再抽出すると行が増える）
CREATE TABLE extractions (
  id              INTEGER PRIMARY KEY,
  article_id      INTEGER NOT NULL REFERENCES articles(id),
  content_hash    TEXT NOT NULL,            -- 抽出時点の記事ハッシュ
  prompt_version  TEXT NOT NULL,
  provider        TEXT NOT NULL,
  model           TEXT NOT NULL,
  status          TEXT NOT NULL,            -- extracted / needs_review / failed
  review_reasons  TEXT,                     -- JSON配列
  error           TEXT,
  is_current      INTEGER NOT NULL DEFAULT 1, -- 記事ごとに最新の1件だけ1
  created_at      TEXT NOT NULL
);

-- エントリ
CREATE TABLE entries (
  id               INTEGER PRIMARY KEY,
  extraction_id    INTEGER NOT NULL REFERENCES extractions(id),
  type             TEXT NOT NULL,
  title            TEXT NOT NULL,
  service          TEXT NOT NULL,
  start            TEXT,
  start_time       TEXT,
  end              TEXT,
  end_time         TEXT,
  open_ended       INTEGER NOT NULL DEFAULT 0,
  start_is_deadline INTEGER NOT NULL DEFAULT 0,
  calendar_start   TEXT,
  calendar_end     TEXT,
  date_text        TEXT,
  evidence         TEXT,
  confidence       REAL,
  hidden           INTEGER NOT NULL DEFAULT 0 -- 手動非表示・取り消し適用
);
CREATE INDEX idx_entries_calendar ON entries(calendar_start, calendar_end);

CREATE TABLE entry_songs (
  entry_id INTEGER NOT NULL REFERENCES entries(id),
  position INTEGER NOT NULL,
  title    TEXT NOT NULL,
  PRIMARY KEY (entry_id, position)
);

CREATE TABLE cancellations (
  id            INTEGER PRIMARY KEY,
  extraction_id INTEGER NOT NULL REFERENCES extractions(id),
  target_type   TEXT NOT NULL,
  title         TEXT,
  songs         TEXT,                       -- JSON配列
  evidence      TEXT,
  confidence    REAL,
  applied_to    INTEGER REFERENCES entries(id) -- 照合済みなら対象エントリ
);

-- 手動修正（抽出結果を直接書き換えず、上書きとして持つ）
CREATE TABLE entry_overrides (
  entry_id   INTEGER PRIMARY KEY REFERENCES entries(id),
  patch      TEXT NOT NULL,                 -- 上書きするフィールドのJSON
  note       TEXT,
  updated_at TEXT NOT NULL
);
```

メモ:

- 表示APIは `is_current = 1` の抽出に属し、`hidden = 0` のエントリを返す。`entry_overrides` を適用してから返す
- 楽曲は検索用に別テーブルにしたが、JSON列で十分ならまとめてもよい
- マイグレーションは `wrangler d1 migrations` で管理する

## 処理の変更点

- **差分抽出**: `content_hash` と `prompt_version` が前回と同じ記事はLLMを呼ばない。プロンプト改訂時だけ全件再抽出
- **記事をまたぐ処理**: 取り消し・延期の照合、同一告知の重複照合はDB上の既存エントリと突き合わせる（今は1回の実行内だけ）
- **失敗の再試行**: `failed` は次回のCronで再投入。回数上限を持たせる
- **レビュー**: `needs_review` を管理画面で一覧し、承認・修正・非表示を記録する。カレンダー側で要確認を出すかは別途決める

## フェーズ

1. **D1とAPIの用意**
   - Workersプロジェクト作成（`wrangler`）、D1作成、スキーマのマイグレーション
   - `entries.json` を D1 に流し込むインポートスクリプト（Python側に `mg-export-d1` のようなコマンドを追加、またはSQLを生成して `wrangler d1 execute`）
   - `GET /api/entries` を実装
2. **表示をWorkersへ**
   - `docs/` の静的ファイルを Static Assets で配信
   - `calendar.js` の読み込み先を `entries.json` から `/api/entries` に変更（レスポンス形式は当面 `entries.json` 互換にして表示ロジックの変更を最小化）
   - GitHub Pagesは並行運用し、問題なければ停止
3. **収集・抽出の自動化（案A）**
   - GitHub Actionsのスケジュール実行で収集→抽出→D1書き込み
   - 差分抽出を実装
4. **レビュー画面**
   - `/admin` を Cloudflare Access で保護
   - `needs_review` の一覧・修正・非表示、取り消しの手動適用
5. **（任意）Cloudflare内で完結させる（案C）**
   - 収集をCron Trigger、抽出をQueues consumerに移す
   - Python側のテストケースをTS側にも移植して挙動をそろえる

## 確認・検討事項

- Workersの無料枠/有料プランで足りるか（Cronの実行時間、サブリクエスト数、Queues、D1の容量・行読み取り数）
- LLM呼び出し1回が長い（現在タイムアウト120秒）。Workers上で実行する場合の待ち時間の扱い
- 公式サイトへのアクセス間隔（現在1秒）をCron/Queuesでどう守るか。Cloudflareの送信元IPからのアクセスが弾かれないか
- 公式サイトの規約上、本文を保存・再配信してよい範囲（公開APIでは本文を返さず、出典リンクとエントリだけ返す）
- 独自ドメインを使うか、`*.workers.dev` で済ませるか
- 過去エントリの扱い（今は自動削除しない。APIの期間指定で絞るだけでよいか）
- `entries.json` のスキーマ変更（`schema_version`）とD1マイグレーションの対応をどう管理するか
