# mg-update-calendar

CHUNITHM・maimai・オンゲキ・海外版CHUNITHMの公式お知らせを収集し、OpenAIまたはDeepSeekのAPIで楽曲追加やイベントなどの告知を抽出するツールです。抽出結果は付属の静的カレンダーで表示できます。

処理は「記事を収集 → 告知を抽出 → カレンダーに反映」の3段階です。以下のコマンドはリポジトリのルートで実行してください。例はWindows / PowerShell向けです。

| やりたいこと | コマンド | 入力 | 出力・結果 |
| --- | --- | --- | --- |
| 公式お知らせを収集する | `uv run mg-update-calendar` | 公式サイト | 記事のJSON |
| カレンダー用の告知を抽出する | `uv run mg-extract-entries` | 記事のJSON | 抽出結果のJSON。APIキーが必要 |
| カレンダーに反映する | `Copy-Item entries.json docs/entries.json` | 抽出結果のJSON | 表示用データを置き換える |
| カレンダーを見る | `uv run python -m http.server 8000 --directory docs` | `docs/` | ブラウザーで表示 |

`mg-update-calendar`は記事収集だけを行います。AI抽出やカレンダーへの反映には、後続のコマンドも実行してください。

## 初回の準備

Gitとuvを使います。Pythonは`.python-version`で指定した3.12をuvが用意します。uvをインストール済みなら、最初のコマンドは省略してください。

```powershell
irm https://astral.sh/uv/install.ps1 | iex
```

リポジトリを取得し、依存関係をインストールします。取得済みなら、そのディレクトリで`uv sync`を実行してください。

```powershell
git clone https://github.com/Qman11010101/mg-update-calendar.git
cd mg-update-calendar
uv sync
```

AI抽出を使う場合は、リポジトリのルートに`.env`を作成します。

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=自分のAPIキー
```

環境変数で設定する場合は、PowerShellで次を実行してください。

```powershell
$env:OPENAI_API_KEY = "自分のAPIキー"
```

DeepSeekを使う場合は、`.env`を次のように設定します。

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=自分のAPIキー
DEEPSEEK_MODEL=deepseek-flash
```

`deepseek-flash`はDeepSeek V4.1 FlashのAPIモデル名です。[公式ドキュメント](https://api-docs.deepseek.com/updates/)

`mg-extract-entries`は実行ディレクトリの`.env`を自動で読み込みます。設定は既存の環境変数、`.env`、既定値の順で優先します。

| 設定 | OpenAI | DeepSeek |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai`（省略時の既定値） | `deepseek` |
| APIキー | `OPENAI_API_KEY` | `DEEPSEEK_API_KEY` |
| モデル設定 | `OPENAI_MODEL` | `DEEPSEEK_MODEL` |
| 既定モデル | `gpt-5.6-luna` | `deepseek-flash` |

両方のAPIキーとモデルを設定しておき、`LLM_PROVIDER`だけで切り替えられます。選択したプロバイダーのAPIキーだけが必要です。


## 記事収集からカレンダー表示まで

### 1. 記事を収集する

`--game`を省略すると、全4ゲームの一覧ページを各1ページ取得し、記事詳細を含めて`news_all.json`に保存します。公開日・タイトル・画像URL・本文のプレーンテキストとMarkdownを収集します。

```powershell
uv run mg-update-calendar
```

1ゲームだけを取得する場合は`--game`を指定してください。

| `--game`の値 | 対象 |
| --- | --- |
| `chunithm` | 国内版CHUNITHM |
| `maimai` | maimai |
| `ongeki` | オンゲキ |
| `chunithm_intl` | 海外版CHUNITHM |
| `all` | 上記の全4ゲーム |

たとえばmaimaiだけを収集する場合は、次のコマンドです。

```powershell
uv run mg-update-calendar --game maimai
```

ゲームを絞った場合も保存先は`news_all.json`です。後続の抽出は同じファイルを読み込みます。

### 2. AIで告知を抽出する

`news_all.json`を読み、記事ごとに選択したプロバイダーのAPIへ送信します。抽出結果は`entries.json`に保存します。

```powershell
uv run mg-extract-entries
```

抽出単位を「エントリ」と呼びます。1記事に楽曲追加・イベント開催・コース追加が含まれる場合、それぞれを別のエントリとして保存します。同日・同種・同条件の複数曲追加は1エントリにまとめます。

### 3. 結果を確認してカレンダーに反映する

`entries.json`の記事ごとの`status`を確認してください。

| `status` | 意味 | 確認するフィールド |
| --- | --- | --- |
| `extracted` | 抽出成功。自動検証で要確認事項なし | `entries` |
| `needs_review` | 抽出結果に確認事項あり | `entries`、`cancellations`、`review_reasons` |
| `failed` | 抽出失敗。その記事のエントリは空 | `error` |

自動検証だけでは、内容や日時の意味が正しいとは保証できません。要確認事項や失敗を確認したうえで、表示用データにコピーしてください。

```powershell
Copy-Item entries.json docs/entries.json
```

カレンダーには要確認のエントリも掲載されますが、要確認ラベルや確認理由は表示されません。取り消しは表示されず、過去のエントリも自動では削除されません。

### 4. カレンダーを表示する

```powershell
uv run python -m http.server 8000 --directory docs
```

ブラウザーで[http://localhost:8000/](http://localhost:8000/)を開きます。サーバーは`Ctrl+C`で停止できます。

JSONの読み込みにはHTTPサーバーが必要です。表示仕様とGitHub Pagesでの公開方法は[カレンダーのREADME](docs/README.md)を参照してください。

## 再実行・上書き・中断

記事収集は`news_all.json`、AI抽出は`entries.json`を置き換えます。記事収集は既存のJSONに追記せず、AI抽出も保存済み結果から再開しません。再実行すると全対象記事を再抽出します。以前の結果を残す場合は、実行前にファイルをコピーしてください。

AI抽出は既定で最大5件を並行実行し、完了した記事から結果を保存します。出力配列は入力記事の順序を保ちます。`Ctrl+C`で中断すると新しい記事の送信を止め、送信済みの処理が終了するまで待ちます。保存済みの結果は出力ファイルに残ります。

`mg-extract-entries`の終了コードは次のとおりです。`needs_review`だけなら`0`になるため、終了コードと抽出結果の両方を確認してください。

| 終了コード | 意味 |
| --- | --- |
| `0` | 処理完了。抽出失敗なし |
| `1` | 記事の抽出失敗あり。他の記事は処理を継続 |
| `2` | 入力・設定・保存エラー |
| `130` | キーボード操作による中断 |

ルートのJSONと`.env`はGit管理対象外です。公開用の`docs/entries.json`は例外としてGitに含めます。`Copy-Item`はローカルのデータ更新です。`docs/`の変更を`main`へpushすると、GitHub Actionsでサイトに反映されます。サイトの公開手順は[カレンダーのREADME](docs/README.md)を参照してください。

## コマンドのオプション

### 記事収集用の`mg-update-calendar`

| オプション | 説明 | 既定値 |
| --- | --- | --- |
| `--game` | `chunithm` / `maimai` / `ongeki` / `chunithm_intl` / `all` | `all` |
| `--max-pages` | ゲームごとの一覧ページ数。0以下で全ページ巡回 | `1` |

保存先は常に`news_all.json`です。記事詳細を含め、指定ページ内の全記事を収集します。リクエスト間隔は1秒で、ゲームをまたいでも維持します。

### AI抽出用の`mg-extract-entries`

引数は不要です。`news_all.json`の全記事を読み込み、`entries.json`に保存します。ファイル名は固定で、実行ディレクトリを基準にします。収集と抽出は同じディレクトリで実行してください。

モデルは`.env`の`OPENAI_MODEL`または`DEEPSEEK_MODEL`で指定できます。APIへの同時リクエスト数は5、1記事あたりの最大出力トークン数は8192、タイムアウトは120秒です。

ヘルプは次のコマンドで表示できます。

```powershell
uv run mg-update-calendar --help
uv run mg-extract-entries --help
```

## 開発時の検証

Pythonのテストとカレンダー表示ロジックのテストを実行します。後者にはNode.jsが必要です。

```powershell
uv run python -m unittest discover -s tests -v
node tests/test_calendar.cjs
```

抽出テストはAPI通信をモックに置き換えます。表示側のテストは日付配置・正式日時・重複統合・出典リンク・検索を検証します。APIキーや外部通信は不要です。実モデルの抽出精度は、別途APIへ接続して確認してください。

## 抽出結果と判定仕様

### JSONの構造

`entries.json`は`schema_version`・`prompt_version`・`model`・`mode`と、
記事ごとの結果配列`articles`を持つ。`schema_version`は`4`、`prompt_version`は`"5"`。各記事の結果には次のフィールドを含む。

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
対象サービスの`service`、単日の期限を表す`start_is_deadline`、表示用の`calendar_start`・`calendar_end`も持つ。
表示用の日付は保存時にコードで生成し、AIの出力スキーマには含めない。

### 所属イベントと自動グループ化

AIは所属イベントの正式名称を`event_name`、その所属関係を示す連続した原文引用を`event_evidence`に出力する。
所属先が不明な項目や独立した告知では両方を`null`にする。同じ記事・日程・作品だけでは所属関係を推定しない。
名称には復刻・回次・弾数を残す。別名や略称の推測照合は行わない。

プログラムは名称の全角・半角をNFKCで正規化し、連続する空白を1つにそろえる。
ゲーム・対象サービス・正規化した名称・正式な開始日時と終了日時の組み合わせから、SHA-256で`event_id`を生成する。
同じ組み合わせは出典記事や処理順にかかわらず同じIDになり、別名は別IDになる。
原文引用が記事内に存在して名称を含むこと、確信度が0.8以上であること、対象サービスと開始・終了日が判明していることを条件とする。
期限のみの項目、終了日不明、期間の矛盾、対象サービス不明、原文根拠不足ではIDを付けない。
`event_id`はプログラムが保存時に生成し、AIの出力スキーマには含めない。

開催中カードはゲーム・対象サービス・イベントID・表示期間が一致する項目をまとめる。
IDのない項目は単独表示する。所属イベントが同じでも期間が違う項目は別カードにする。
同一告知の重複統合は別処理で行い、出典を保持する。イベントIDが異なる項目は重複統合しない。
抽出結果に所属情報がない場合も表示できる。所属情報を付けるには記事を再抽出する。

### エントリの分類

共通の種類は`song_add`（新曲・復活曲）、`song_unlock`（一般開放・解禁条件緩和）、
`goods_campaign`（グッズキャンペーン）、`version_launch`、`maintenance`、`service_change`、`other`。
`goods_campaign`は実物のグッズを交換・配布・抽選で入手できるキャンペーン。
ゲーム内アイテムやログインボーナスは既存の種類で扱う。
コラボイベントと併催される場合も別エントリに分け、曲名は必須としない。
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

### 抽出対象とタイトル

参照先のお知らせ記事は別途収集・抽出される前提で、他記事への誘導や背景説明を抽出対象から外す。
詳細記事への案内として掲載された名前・概要・リンク付きバナーは、日付があっても抽出しない。
別の告知の前提として言及されるバージョン稼働なども独立したエントリにしないが、
その記述は抽出対象の開催日を判断する根拠として利用できる。
除外は該当箇所だけに適用し、同じ記事が直接告知する楽曲追加などは保持する。
遊び方・参加方法・外部サイトへの補足リンクがあるだけでは除外しない。
直接告知される中止・取り消し・延期・日程変更は、元記事へのリンクや誘導部分に含まれていても通常どおり扱う。
除外した内容を`other`に置き換えず、除外の報告や除外部分の日時・曲名不足だけでは要確認にしない。
この判定はプロンプトで指示し、受信後にコードで強制するものではない。

イベントや期間を持つコンテンツのタイトルは対象名を中心にし、告知表現の「開催」「オープン」「開始」「開催中」は付けない。
コラボイベントは`event`・`「〇〇」コラボイベント`にそろえる。独立したちほー追加は`area_add`・正式名称の`〇〇ちほー`とする。
コラボイベントと同一内容・期間のイベント用マップ・ちほー・チャプターは、記事の表記によらず`event`にまとめ、タイトルにコンテンツ名を併記しない。
コラボかどうか不明な場合は推測せず、独立したコンテンツとして分類する。
復刻・回次・対象作品名などの識別情報と正式名称は保持する。
楽曲・譜面追加やバージョン稼働など、告知内容を識別する語は保持する。
この命名は抽出プロンプトで指示する。

復刻イベントも`event`とし、タイトルに復刻であることを残す。
独立したコンテンツ追加や、期間の異なるランキング・ミッションなどは別エントリにする。

### 中止・取り消し・延期

収録見合わせや中止・取り消しは`entries`に出さず、`cancellations`配列に保持する。
各取り消しには`target_type`、`title`、`songs`、`evidence`、`confidence`を持たせる。
対象が不明なら`target_type: other`として要確認にする。
原文根拠・確信度を検証し、元エントリとの照合が必要な取り消しはすべて`needs_review`にする。
記事をまたぐ元エントリの照合・更新は後続処理で扱い、抽出時には自動適用しない。
延期は変更後の日付で該当種類のエントリを出し、延期と元日付を要確認事項に記録する。

### 日付と期間

日付は`YYYY-MM-DD`、時刻は`HH:MM`。不明な日時は`null`で保持する。
単日は`end: null`・`open_ended: false`、継続が明示された告知は`open_ended: true`。
期間イベントと恒久的な楽曲追加は、それぞれの期間を保持する。
年の補完や曖昧な情報はAIに`review_notes`を返させ、要確認理由へ含める。

### メンテナンス前の最終利用日

記事のゲーム分類は変更せず、各エントリの対象を`service`に持つ。
ゲーム本体と対応するNETは同じサービスIDを使い、カードメイカーは`card_maker`として別登録する。
対象が判断できない場合や未登録のサービスは`null`とし、日付を補正せず要確認にする。

| サービスID | 登録済みの通常メンテナンス（日本時間） | 設定の参照元 |
| --- | --- | --- |
| `chunithm` | 2:00〜7:00 | [CHUNITHM公式](https://info-chunithm.sega.jp/1042/) |
| `maimai` | 4:00〜7:00 | [maimai公式](https://info-maimai.sega.jp/1562/) |
| `ongeki` | 4:00〜7:00 | [オンゲキ公式](https://info-ongeki.sega.jp/2340/) |
| `card_maker` | 2:00〜7:00 | [カードメイカーの公式告知](https://info-maimai.sega.jp/1562/) |

設定は`src/mg_update_calendar/services.py`に集約する。新しいゲーム・関連サービスは公式情報を確認して個別に登録する。
海外版には国内版の時刻を適用しない。時刻が10:00でも、通常メンテナンスとして推測しない。

`start_is_deadline`は、単日の終了・停止・締切を表す場合に`true`。
期間のある告知、開始・追加・解禁・実装・メンテナンス開始は`false`。
カードメイカー上の購入・ガチャ・ログインなどが対象と読み取れる場合だけ`service: card_maker`を指定する。
記事にカードメイカーへの言及があるだけでは適用しない。同じ記事でもエントリごとに対象を判定する。

`start`・`start_time`・`end`・`end_time`と原文引用は正式な日時を保持する。
コードで`calendar_start`・`calendar_end`を生成し、終了・停止・締切が0:00から対象サービスの
メンテナンス開始時刻まで（開始時刻を含む）なら、カレンダー用の日付を1日前へ補正する。
開始・追加・解禁やメンテナンスの期間は補正しない。時刻不明の場合も補正しない。
期間の終了は`calendar_end`に反映し、補正すると開始日より前になる場合は原日付を保持して要確認にする。

例として、maimaiの記事にあるカードメイカーの販売停止が9月2日01:59なら、
`service: card_maker`・`start_is_deadline: true`・`calendar_start: 2026-09-01`となる。
正式な`start: 2026-09-02`・`start_time: 01:59`は保持する。

### 原文根拠と要確認判定

`date_text`と`evidence`はタイトル・本文・Markdownのいずれかに連続した原文として
存在するかをコードで検証する。根拠不足、日時の矛盾、開始日不明、`other`、
`confidence < 0.8`、本文不足、公開日不明、AIの確認事項は`needs_review`にする。
この検証だけで抽出内容や日付の意味が正しいと保証するものではない。

APIの拒否、途中終了、不正な構造化出力、通信エラーは`failed`にし、後続記事の処理を続ける。
失敗した記事のエントリは空になるが、告知がなく抽出に成功した空配列とは`status`で区別できる。
APIエラーはSDKの例外名だけを保存する。SDKは一時的な通信エラーを最大2回再試行する。

## 対応範囲と制限

OpenAIはResponses APIのStructured Outputsを使い、Pydanticから生成したJSONスキーマを指定します。DeepSeekはChat Completions APIのJSONモードを使い、同じスキーマをプロンプトに含めます。JSONモードはスキーマへの適合を強制しないため、どちらのプロバイダーでも受信後にPydanticで形式・型・値を検証します。APIキーはリクエストの保存・出力ファイルに含めません。

画像URLは収集しますが、画像そのものはAIへ送信しません。画像内の情報の抽出、表記や分類が異なる項目の記事横断の重複統合、取り消し・延期による既存エントリ更新、キャッシュ、外部カレンダー向けの出力には対応していません。海外版は画像内の情報とタイムゾーンを未確認として扱います。

静的カレンダーでは、ゲーム・種類・タイトル・正式日時・対象サービス・期間指定・対象曲・配置日が完全一致する項目を表示時に統合し、すべての出典を表示します。抽出JSONは記事別に保持します。詳細な判定条件は[カレンダーのREADME](docs/README.md)を参照してください。

## LLM処理の構成

- `src/mg_update_calendar/llm.py`: プロバイダー設定、SDKの生成・終了、APIリクエスト、応答・エラーの共通化。
- `src/mg_update_calendar/prompts.py`: 告知抽出の指示文とプロンプトバージョン。
- `src/mg_update_calendar/extractor.py`: 記事からの入力生成、抽出結果の検証、カレンダー用の日付・イベントIDの生成、並列処理と保存。

別の処理からLLMを呼ぶ場合は、`LLMConfig`で設定した`LLMClient`に`LLMRequest`を渡し、`generate_json()`でJSON文字列を受け取ります。`LLMRequest`には指示文、入力文字列、JSONスキーマ、スキーマ名、最大出力トークン数を指定します。利用側で用途に応じた検証を行ってください。`with LLMClient(config) as client:`で接続を閉じます。

プロバイダーを追加する場合は`JSONGenerator`の`generate_json()`を実装し、設定と`LLMClient`の生成処理に追加します。APIの拒否・出力途中の終了・空応答・SDK例外は`LLMError`で扱います。SDK例外の本文は保存せず、例外名のみを記録します。抽出結果のJSONには`provider`と`model`を保存します。
