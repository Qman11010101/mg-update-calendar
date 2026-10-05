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

**当面はGitHub上（Pages + Actions）で運用し、`needs_review` の修正が回らなくなったらCloudflareへ移行する。**

### 基盤をどこにするか

無料枠は2026-10-05に各公式ページで確認した値。公開用JSONは現在 約296KB（gzip 約33KB、75記事）。1年分の蓄積でgzip 約330KBと仮定して見積もる。

| 案 | 構成 | 無料枠の要点 | 閲覧ごとにDBを引いた場合 | 長所 | 短所 |
| --- | --- | --- | --- | --- | --- |
| **Cloudflare（採用予定）** | Workers + D1 + KV + Access | D1読み取り500万行/日・書き込み10万行/日、Workers 10万リクエスト/日、Static Assetsは無料・無制限。超過時は課金でなくエラー（00:00 UTCにリセット） | 1表示で約7,000行を読む見込みで、1日約700回が上限 | 管理画面のログインをAccessに任せられる。配信・API・DBを1か所で管理できる | Workers（TypeScript）とPython（Actions）の2本立てになる。移行量が多い |
| Supabase + GitHub Pages | Postgres + Supabase Auth + RLS | DB 500MB、転送量5GB/月、APIリクエスト無制限、1週間使わないと一時停止（cronで書き込めば停止しない） | 転送量が先に尽き、1日約500回が上限 | 今のPagesとPythonをほぼそのまま使える | 管理者だけに書き込みを許すのをRLSで書くことになり、設定ミスがそのまま穴になる。修正をすぐ公開するには別の仕掛けが要る |
| Firebase | Firestore + Auth + Hosting | Firestore読み取り5万ドキュメント/日、Hosting転送量360MB/日 | 1エントリ1ドキュメントだと1日十数回で上限 | Authが手軽 | 読み取りをドキュメント単位で数えるので、今回のデータの形に合わない |
| GitHubのみ | Pages + Actions + リポジトリ内の修正ファイル | 実質的な制限なし（Pagesの帯域の目安は100GB/月） | DBなし | 費用も保守もほぼかからない。修正履歴がGitに残る | 管理画面を作りにくい。ログインして修正する運用には向かない |

**どの案でも、閲覧者にDBを直接引かせない。** DBを使うのは取り込みと管理画面だけにし、閲覧には生成済みのスナップショットを返す。こうすれば閲覧数が増えても、DBの無料枠は閲覧数に影響されない。

- Cloudflareの場合：取り込み後または管理画面での保存時に、D1から表示用JSONを生成してKVに置く。`GET /api/entries` はKVを1回読むだけにする
- さらに減らしたい場合は、生成したJSONをStatic Assetsとして再デプロイする。閲覧は完全に無料・無制限になるが、反映には再デプロイが必要
- スナップショットはD1の1行には入れない。1行あたりの上限（約2MB、要確認）に、蓄積が進むと届く可能性がある
- Cache APIは `*.workers.dev` では効かないので、使う場合は独自ドメインが前提

### 当面のGitHub上での運用

- Actionsのスケジュール実行で、収集から差分抽出までを行う。`content_hash` と `prompt_version` が同じ記事はLLMを呼ばない
- 抽出結果は上書きせず蓄積する。収集は一覧の1ページ目だけなので、上書きすると古い告知が消える
- 手動修正は抽出結果とは別のファイル（例：`data/overrides/`）に持ち、再抽出しても消えないようにする。D1に移すときは `entry_overrides` に変換する
- 全件 `extracted` なら `main` へ直接コミットし、`needs_review` か `failed` があればPRを作る
- `GITHUB_TOKEN` によるpushでは `pages.yml` のpushトリガーが起動しない。デプロイは同じワークフロー内で行うか、`workflow_call` で呼ぶ

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
  ├─ GET /api/entries  … カレンダー表示用（KVのスナップショットを返す。D1は読まない）
  └─ /admin/*  … needs_review の確認・修正（Cloudflare Accessで保護）
```

- APIキー（OpenAI / DeepSeek）は Workers Secrets に置く
- 記事本文のHTML・LLMの生レスポンスなど大きいものは必要なら R2 に置き、D1にはキーだけ持つ
- 表示用データは、D1の更新時にスナップショットとしてKVへ書き出す（「基盤をどこにするか」を参照）
- `extractions(article_id, is_current)` と `entries(extraction_id)` にインデックスを張る。D1は返した行数ではなくスキャンした行数で数えるため

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

- Workersの無料枠/有料プランで足りるか（Cronの実行時間、サブリクエスト数、Queues、D1の容量・行読み取り数）。閲覧はスナップショットで返すので、D1の読み取りは取り込みと管理画面の分だけで見積もる
- 無料枠を超えると日本時間9時までエラーになる。その間は前回のスナップショットを返し続けられるか
- LLM呼び出し1回が長い（現在タイムアウト120秒）。Workers上で実行する場合の待ち時間の扱い
- 公式サイトへのアクセス間隔（現在1秒）をCron/Queuesでどう守るか。Cloudflareの送信元IPからのアクセスが弾かれないか
- 公式サイトの規約上、本文を保存・再配信してよい範囲（公開APIでは本文を返さず、出典リンクとエントリだけ返す）
- 独自ドメインを使うか、`*.workers.dev` で済ませるか
- 過去エントリの扱い（今は自動削除しない。APIの期間指定で絞るだけでよいか）
- `entries.json` のスキーマ変更（`schema_version`）とD1マイグレーションの対応をどう管理するか
