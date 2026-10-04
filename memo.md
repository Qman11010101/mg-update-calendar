# ニュース記事からカレンダー用エントリへの加工

## 用語と粒度

個々の告知を「エントリ」と呼ぶ。イベント開催は種類`event`として区別する。
1記事にイベント開催、楽曲追加、コース追加などが含まれる場合は別エントリに分ける。
同日・同種・同条件の複数曲追加はまとめて1エントリにし、曲名を`songs`に持つ。

## 抽出

`mg-update-calendar`で収集したニュースJSONを`mg-extract-entries`で読み込み、
記事ごとにOpenAI Responses APIへ渡す。既定モデルは`gpt-5.6-luna`。
構造化出力は`entries[]`、`cancellations[]`、`review_notes[]`を持つ。
Pydanticのスキーマを厳密なJSONスキーマとして指定し、受信後も検証する。

公開日、ゲーム、タイトル、プレーン本文、Markdown本文を入力に含める。
画像やリンク先の内容は入力に含めない。
本文がない記事はタイトルを根拠に抽出し、要確認とする。

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

日付は`start`・`end`、時刻は`start_time`・`end_time`に分ける。
日時不明は`null`。単日は終了日なし、継続が明示された場合は`open_ended: true`。
イベントに伴う恒久的な楽曲追加にはイベント終了日を流用しない。
過去の報告もあるため、公開日より前の日付を機械的に翌年へ変更しない。
年の補完理由はAIに確認事項として返させる。

## 検証と保存

- `date_text`と`evidence`がタイトル・本文・Markdownのいずれかに部分文字列として存在するか確認する。
- 日時の矛盾、開始日不明、`other`、低い確信度、AIの確認事項は要確認にする。
- 本文不足、公開日不明、海外版のタイムゾーン・画像情報は要確認にする。
- 拒否、途中終了、スキーマ違反、APIエラーは記事単位の失敗として保存する。
- 出力は記事単位で元記事情報、内容ハッシュ、エントリ、確認理由、失敗理由を保持する。
- dry-runではAPIを呼ばず、入力記事・プロンプト・スキーマを含む送信予定リクエストを保存する。

原文引用が存在しても、その引用と日付・内容の対応が正しいかは別途確認が必要。
実モデルの抽出精度はAPI接続時に評価する。

## 後続処理の検討事項

- 内容ハッシュ、モデル、プロンプト、スキーマを使った記事単位のキャッシュ。
- ゲーム・種類・開始日・タイトルを使った記事横断の重複統合。
- 複数の元記事を持つエントリへの取り消し・延期の反映。
- サイト用データとゲーム別・全ゲームのICS出力。
- 海外版の画像入力とタイムゾーンの確認。
- エントリの種類とゲーム内の日付境界の扱い。
