# mg-update-calendar

セガ音ゲーお知らせサイト (CHUNITHM / maimai / オンゲキ / 海外版CHUNITHM) のスクレイピングツール。
記事発表日・タイトル・画像URL・本文 (プレーン + Markdown) をJSON化し、OpenAI APIでカレンダー用のエントリに分解する。

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

## ニュースからエントリを抽出する

個々の告知を「エントリ」と呼ぶ。イベント開催はエントリの種類の一つ。
1記事に楽曲追加・イベント開催・コース追加があれば、それぞれ別エントリに分ける。
同日・同種・同条件の複数曲追加は1エントリにまとめ、曲名を`songs`配列に保持する。

入力はスクレイパーが保存した記事配列。記事ごとにOpenAI Responses APIへ送信し、
Pydanticのスキーマを`text.format`の`json_schema`・`strict: true`として指定する。
受け取ったJSONも同じスキーマで検証する。
既定モデルは`gpt-5.6-luna`。`OPENAI_MODEL`または`--model`で変更できる。

```powershell
uv sync

# APIを呼ばず、プロンプト・記事データ・JSONスキーマを確認する
uv run mg-extract-entries --input news_all.json --output entry_requests.json --dry-run --max-articles 3

# APIを使って抽出する
$env:OPENAI_API_KEY = "自分のAPIキー"
uv run mg-extract-entries --input news_all.json --output entries.json --max-articles 3

# モデルを明示して全記事を処理する
uv run mg-extract-entries --input news_all.json --output entries.json --model gpt-5.6-luna
```

APIキーは環境変数から読み取る。リクエストの保存・出力ファイルには含めない。
`mg-extract-entries`は実行ディレクトリの`.env`を起動時に自動読み込みする。
`OPENAI_API_KEY`と`OPENAI_MODEL`を設定できる。既存の環境変数を優先し、モデルは`--model`が最優先。
`.env`がなくても実行できる。
`--dry-run`は送信予定のリクエストを保存するだけで、抽出済みエントリは生成しない。

| オプション | 説明 | 既定値 |
| --- | --- | --- |
| `--input`, `-i` | 収集済みニュースJSON | 必須 |
| `--output`, `-o` | 抽出結果、またはdry-runのリクエストJSON | `entries.json` |
| `--model` | Structured Outputsに対応するモデル名 | `OPENAI_MODEL`、未設定なら`gpt-5.6-luna` |
| `--max-articles` | 入力順で処理する記事数。0は全件 | `0` |
| `--max-output-tokens` | 1記事あたりの最大出力トークン数 | `8192` |
| `--timeout` | APIリクエストのタイムアウト秒 | `120` |
| `--dry-run` | APIを呼ばず送信予定のリクエストを出力 | 無効 |

### 出力形式

`entries.json`は`schema_version`・`prompt_version`・`model`・`mode`と、
記事ごとの結果配列`articles`を持つ。`schema_version`は`2`、`prompt_version`は`"3"`。各記事の結果には次のフィールドを含む。

| フィールド | 内容 |
| --- | --- |
| `source` | ゲーム、記事URL、公開日、タイトル |
| `content_hash` | AIへ渡す記事データのSHA-256 |
| `status` | `extracted`、`needs_review`、`failed` |
| `entries` | その記事から抽出したエントリの配列 |
| `cancellations` | 取り消し対象と原文根拠の配列。カレンダー項目としては表示しない |
| `review_reasons` | 要確認の理由 |
| `error` | 失敗理由。成功時は`null` |

エントリには`type`・`title`・`start`・`start_time`・`end`・`end_time`・
`open_ended`・`songs`・`date_text`・`evidence`・`confidence`を持たせる。
共通の種類は`song_add`（新曲・復活曲）、`song_unlock`（一般開放・解禁条件緩和）、
`version_launch`、`maintenance`、`service_change`、`other`。
ゲーム別の種類は次のとおり。送信スキーマと受信時の検証で、そのゲームの種類だけを許可する。

| ゲーム | 種類 |
| --- | --- |
| CHUNITHM 国内・海外 | `event`、`map_add`、`quest`、`mission`、`course_add`、`ultima_add`、`worlds_end_add` |
| maimai | `event`、`area_add`、`friend_battle`、`course_add`、`remaster_add`、`dx_chart_add`、`standard_chart_add`、`utage_add` |
| オンゲキ | `event`、`chapter_add`、`ranking`、`technical_challenge`、`gacha`、`login_bonus`、`mission`、`lunatic_add` |

`map_add`は新マップ・拡張、`area_add`はちほー追加・拡張、`chapter_add`はチャプター追加。
`course_add`はCHUNITHMのクラス認定、maimaiの段位認定コース追加。
`friend_battle`はオトモダチ対戦シーズン、`ranking`はランキング・ぷちランキングイベント。
`quest`はチュウニズムクエスト、`mission`はミッション。
譜面追加はULTIMA、WORLD’S END、Re:MASTER、でらっくす、スタンダード、宴、LUNATICを区別する。
新曲に付属する通常譜面は`song_add`に含め、既存曲への追加譜面をゲーム別の種類で扱う。
楽曲追加・解禁・譜面追加（`song_add`、`song_unlock`、`ultima_add`、`worlds_end_add`、
`remaster_add`、`dx_chart_add`、`standard_chart_add`、`utage_add`、`lunatic_add`）は、
`songs`が空、または空文字・空白だけの曲名しかない場合、`entries`から除外する。
プロンプトで曲名のない告知を出力しないよう指定し、受信後にもコードで除外する。
曲名を推測したり、仮の曲名で埋めたり、`event`や`other`に置き換えたりしない。
通常イベント・バージョン稼働など、曲名を必要としない種類と`cancellations`はこの除外の対象外。
AIが返した情報不足などの確認事項は保持する。

復刻イベントも`event`とし、タイトルに復刻であることを残す。
同じコラボのイベントとイベント用マップ・ちほー・チャプターが同一内容・期間なら`event`にまとめる。
独立したコンテンツ追加や、期間の異なるランキング・ミッションなどは別エントリにする。

収録見合わせや中止・取り消しは`entries`に出さず、`cancellations`配列に保持する。
各取り消しには`target_type`、`title`、`songs`、`evidence`、`confidence`を持たせる。
対象が不明なら`target_type: other`として要確認にする。
原文根拠・確信度を検証し、元エントリとの照合が必要な取り消しはすべて`needs_review`にする。
記事をまたぐ元エントリの照合・更新は後続処理で扱い、抽出時には自動適用しない。
延期は変更後の日付で該当種類のエントリを出し、延期と元日付を要確認事項に記録する。

日付は`YYYY-MM-DD`、時刻は`HH:MM`。不明な日時は`null`で保持する。
単日は`end: null`・`open_ended: false`、継続が明示された告知は`open_ended: true`。
期間イベントと恒久的な楽曲追加は、それぞれの期間を保持する。
年の補完や曖昧な情報はAIに`review_notes`を返させ、要確認理由へ含める。

`date_text`と`evidence`はタイトル・本文・Markdownのいずれかに連続した原文として
存在するかをコードで検証する。根拠不足、日時の矛盾、開始日不明、`other`、
`confidence < 0.8`、本文不足、公開日不明、AIの確認事項は`needs_review`にする。
この検証だけで抽出内容や日付の意味が正しいと保証するものではない。

APIの拒否、途中終了、不正な構造化出力、通信エラーは`failed`にし、後続記事の処理を続ける。
失敗した記事のエントリは空になるが、告知がなく抽出に成功した空配列とは`status`で区別できる。
APIエラーはSDKの例外名だけを保存する。SDKは一時的な通信エラーを最大2回再試行する。

結果は記事ごとにファイルへ保存する。実行し直すと出力を置き換え、全対象記事を再抽出する。
終了コードは成功・要確認のみなら`0`、記事の抽出失敗があれば`1`、入力・設定・保存エラーなら`2`。

画像入力、記事をまたぐ重複統合、取り消し・延期による既存エントリ更新、キャッシュ、
カレンダー出力は対象外。海外版は本文とタイトルだけを扱い、画像内の情報と
タイムゾーンを未確認として扱う。

### 検証

```powershell
uv run python -m unittest discover -s tests -v
```

テストはOpenAI SDKのHTTP通信をモックに置き換える。APIキーや外部通信は不要。
実モデルの抽出精度はAPIへ接続して別途確認する。

API仕様は[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)、
既定モデルの対応機能は[GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)を参照。
