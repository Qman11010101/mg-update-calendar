from __future__ import annotations

from datetime import date
import re
import unicodedata
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Game = Literal["chunithm", "maimai", "ongeki"]
Service = Literal["chunithm", "maimai", "ongeki", "card_maker"]
CommonEntryType = Literal[
    "song_add", "song_unlock", "goods_campaign", "version_launch", "maintenance", "service_change", "other",
]
ChunithmEntryType = Literal[
    "event", "map_add", "quest", "mission", "course_add", "ultima_add", "worlds_end_add", "login_bonus",
    "avatar_costume",
]
MaimaiEntryType = Literal[
    "event", "area_add", "friend_battle", "course_add", "remaster_add",
    "dx_chart_add", "standard_chart_add", "utage_add",
]
OngekiEntryType = Literal[
    "event", "chapter_add", "ranking", "technical_challenge", "gacha",
    "login_bonus", "mission", "lunatic_add",
]
EntryType = Literal[CommonEntryType, ChunithmEntryType, MaimaiEntryType, OngekiEntryType]
GAME_ENTRY_TYPES: dict[Game, tuple[str, ...]] = {
    "chunithm": get_args(CommonEntryType) + get_args(ChunithmEntryType),
    "maimai": get_args(CommonEntryType) + get_args(MaimaiEntryType),
    "ongeki": get_args(CommonEntryType) + get_args(OngekiEntryType),
}
ENTRY_LABELS = {
    "song_add": "楽曲追加（新曲・復活曲）", "song_unlock": "楽曲の一般開放・解禁条件緩和",
    "goods_campaign": "グッズキャンペーン",
    "version_launch": "バージョン稼働", "maintenance": "メンテナンス",
    "service_change": "サービス変更", "other": "その他（要確認）",
    "event": "コラボなどのイベント開催", "map_add": "新マップ・マップ拡張",
    "quest": "チュウニズムクエスト", "mission": "ミッション",
    "course_add": "クラス認定・段位認定のコース追加", "ultima_add": "ULTIMA譜面追加",
    "worlds_end_add": "WORLD’S END譜面追加", "area_add": "ちほー追加・拡張",
    "friend_battle": "オトモダチ対戦シーズン", "remaster_add": "Re:MASTER譜面追加",
    "dx_chart_add": "でらっくす譜面追加", "standard_chart_add": "スタンダード譜面追加",
    "utage_add": "宴譜面追加", "chapter_add": "チャプター追加",
    "ranking": "ランキング・ぷちランキングイベント", "technical_challenge": "テクニカルチャレンジ",
    "gacha": "ガチャ", "login_bonus": "ログインボーナス", "lunatic_add": "LUNATIC譜面追加",
    "avatar_costume": "アバターコスチューム",
}
# 楽曲・譜面追加系の種類。曲名は`songs`に持ち、タイトルは種類の表記だけにする（ULTIMA譜面追加など）。
SONG_TYPES = frozenset({
    "song_add", "song_unlock", "ultima_add", "worlds_end_add", "remaster_add",
    "dx_chart_add", "standard_chart_add", "utage_add", "lunatic_add",
})
# タイトルを種類の表記だけにする種類。アバターコスチュームは同時期のマップ・イベントに紐づかない。
# 楽曲・譜面追加は、所属先の対象名があるときだけ「「コラボ先」楽曲追加」のように対象名を付ける。
LABEL_ONLY_TYPES = SONG_TYPES | {"avatar_costume"}
# 正式名称がないときのタイトルの書式。{subject}は対象名、{label}は種類の表記。ここにない種類はDEFAULT_TITLE_FORMATを使う。
DEFAULT_TITLE_FORMAT = "「{subject}」{label}"  # 「GUILTY GEAR -STRIVE-」コラボイベント、「Mate ep. III」マップ
TITLE_FORMATS = {
    "friend_battle": "{label} {subject}",  # オトモダチ対戦 シーズン29
    "area_add": "{subject} {label}",  # ヒメヒナちほー 復刻、天界ちほー9 拡張
    "goods_campaign": "{subject} {label}",  # オンゲキ Re:Fresh オリジナルグッズプレゼントキャンペーン 第14弾、デジタルアイテムキャンペーン 第3弾
    "version_launch": "{subject} {label}",  # CHUNITHM Mate 稼働
    "service_change": "{subject} {label}",  # カードメイカー CHUNITHMガチャ機能 提供終了、でらっくすパス新規販売停止
    "other": "{subject} {label}",  # まじかるパス キャラクター追加
}
# 対象名がこの語を含むとき、labelの先頭からこの語までを取り除く。何も残らなければ対象名だけにする。
LABEL_WORDS_IN_SUBJECT = {
    "area_add": "ちほー",  # ヒメヒナちほー ＋ ちほー復刻 → ヒメヒナちほー 復刻
    "goods_campaign": "キャンペーン",  # デジタルアイテムキャンペーン 第3弾 ＋ グッズキャンペーン → デジタルアイテムキャンペーン 第3弾
}
# 一定期間存在し続けるコンテンツの種類。追加は点の出来事なので、エントリのタイトルではlabel末尾の「追加」を省く。
# 拡張は既存コンテンツへの出来事として残し、「追加・拡張」も告知内容が変わらないようそのままにする。
CONTENT_TYPES = frozenset({"map_add", "area_add", "chapter_add"})  # 「Mate ep. III」マップ、BLACK ROSEちほー11
# 内容を表さない総称のlabel。対象名があれば対象名だけにする。
GENERIC_LABELS = {
    "service_change": "サービス変更",  # でらっくすパス新規販売停止 ＋ サービス変更 → でらっくすパス新規販売停止
}
Clock = Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]


class Article(BaseModel):
    game: Game
    url: str = Field(min_length=1)
    date: date | None
    title: str = Field(min_length=1)
    body_text: str = ""
    body_markdown: str = ""

    @field_validator("date", mode="before")
    @classmethod
    def missing_publication_date(cls, value: object) -> object:
        return None if value == "" else value


class StructuredModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Song(StructuredModel):
    title: str
    artist: str | None


class Entry(StructuredModel):
    type: EntryType
    subject: str | None
    label: str = Field(min_length=1)
    official_name: str | None
    service: Service | None
    start_is_deadline: bool
    start: date | None
    start_time: Clock | None
    end: date | None
    end_time: Clock | None
    open_ended: bool
    songs: list[Song]
    date_text: str
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Cancellation(StructuredModel):
    target_type: EntryType
    subject: str | None
    label: str = Field(min_length=1)
    official_name: str | None
    songs: list[Song]
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Extraction(StructuredModel):
    entries: list[Entry]
    cancellations: list[Cancellation]
    notes: list[str]
    review_notes: list[str]


def _corner_brackets(text: str) -> str:
    return text.replace("『", "「").replace("』", "」")


def subject_key(subject: str | None) -> str | None:
    """同じ作品・企画かを比べるためのキー。表記ゆれになりやすい空白と括弧を除く。"""
    key = re.sub(r"[\s「」『』【】]", "", unicodedata.normalize("NFKC", subject or ""))
    return key or None


def display_title(item: Entry | Cancellation) -> str:
    """対象名・種類・正式名称から表示用のタイトルを組み立てる。"""
    label = _corner_brackets(item.label.strip())
    item_type = item.type if isinstance(item, Entry) else item.target_type
    subject = _corner_brackets((item.subject or "").strip())
    inner = subject[1:-1]
    if subject[:1] == "「" and subject[-1:] == "」" and "「" not in inner and "」" not in inner:
        subject = inner.strip()
    songs = [song.title.strip() for song in item.songs if song.title.strip()]
    # 楽曲・譜面追加は曲名を含めず、所属先の対象名だけを付ける。取り消しはどの曲かが分かるよう曲名を残す。
    if isinstance(item, Entry) and item_type in LABEL_ONLY_TYPES:
        song_keys = {subject_key(song) for song in songs}
        if item_type not in SONG_TYPES or not subject or subject_key(subject) in song_keys:
            return label
        return DEFAULT_TITLE_FORMAT.format(subject=subject, label=label)
    if not subject and len(songs) == 1:
        subject = _corner_brackets(songs[0])
    official = _corner_brackets((item.official_name or "").strip())
    key = subject_key(subject)
    official_key = subject_key(official) or ""
    # 種類名と「対象名」の語順を変えただけの表記や、対象名を欠く・対象名そのものの表記は正式名称として扱わない。
    reordered = any(subject_key(quoted) == key for quoted in re.findall(r"「([^「」]*)」", official))
    if official and not (key and (reordered or key not in official_key or key == official_key)):
        return official
    if not subject:
        return f"{label}（{len(songs)}曲）" if len(songs) > 1 else label
    word = LABEL_WORDS_IN_SUBJECT.get(item_type)
    if word and word in subject and word in label:
        label = label.split(word, 1)[1].strip()
    if isinstance(item, Entry) and item_type in CONTENT_TYPES and "拡張" not in label:
        label = label.removesuffix("追加").strip()
    if not label or label == GENERIC_LABELS.get(item_type):
        return subject
    # 対象名と種類の一方が他方を含む場合は、同じ語を重ねない。
    if subject in label:
        return label
    if label in subject:
        return subject
    return TITLE_FORMATS.get(item_type, DEFAULT_TITLE_FORMAT).format(subject=subject, label=label)


def extraction_schema(game: Game) -> dict:
    schema = Extraction.model_json_schema()
    allowed = list(GAME_ENTRY_TYPES[game])
    schema["$defs"]["Entry"]["properties"]["type"]["enum"] = allowed
    schema["$defs"]["Cancellation"]["properties"]["target_type"]["enum"] = allowed
    return schema
