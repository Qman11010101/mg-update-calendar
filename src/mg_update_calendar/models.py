from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Game = Literal["chunithm", "maimai", "ongeki", "chunithm_intl"]
Service = Literal["chunithm", "maimai", "ongeki", "card_maker", "chunithm_intl"]
CommonEntryType = Literal[
    "song_add", "song_unlock", "goods_campaign", "version_launch", "maintenance", "service_change", "other",
]
ChunithmEntryType = Literal[
    "event", "map_add", "quest", "mission", "course_add", "ultima_add", "worlds_end_add",
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
    "chunithm_intl": get_args(CommonEntryType) + get_args(ChunithmEntryType),
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


class Entry(StructuredModel):
    type: EntryType
    title: str = Field(min_length=1)
    service: Service | None
    event_name: str | None
    event_evidence: str | None
    start_is_deadline: bool
    start: date | None
    start_time: Clock | None
    end: date | None
    end_time: Clock | None
    open_ended: bool
    songs: list[str]
    date_text: str
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Cancellation(StructuredModel):
    target_type: EntryType
    title: str = Field(min_length=1)
    songs: list[str]
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class Extraction(StructuredModel):
    entries: list[Entry]
    cancellations: list[Cancellation]
    review_notes: list[str]


def extraction_schema(game: Game) -> dict:
    schema = Extraction.model_json_schema()
    allowed = list(GAME_ENTRY_TYPES[game])
    schema["$defs"]["Entry"]["properties"]["type"]["enum"] = allowed
    schema["$defs"]["Cancellation"]["properties"]["target_type"]["enum"] = allowed
    return schema
