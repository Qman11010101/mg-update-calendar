from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from mg_update_calendar.models import Entry, Game


@dataclass(frozen=True)
class Maintenance:
    start: str
    end: str
    source_url: str


SERVICE_MAINTENANCE = {
    "chunithm": Maintenance("02:00", "07:00", "https://info-chunithm.sega.jp/1042/"),
    "maimai": Maintenance("04:00", "07:00", "https://info-maimai.sega.jp/1562/"),
    "ongeki": Maintenance("04:00", "07:00", "https://info-ongeki.sega.jp/2340/"),
    "card_maker": Maintenance("02:00", "07:00", "https://info-maimai.sega.jp/1562/"),
}


def maintenance_for(entry: Entry, game: Game) -> Maintenance | None:
    # 海外版には国内版や国内カードメイカーの時刻を流用しない。
    if game == "chunithm_intl" or entry.service not in (game, "card_maker"):
        return None
    return SERVICE_MAINTENANCE.get(entry.service)


def last_available_day(day: date | None, clock: str | None, maintenance: Maintenance) -> date | None:
    if day and clock and clock <= maintenance.start and day > date.min:
        return day - timedelta(days=1)
    return day


def calendar_dates(entry: Entry, game: Game) -> dict[str, str | None]:
    start, end = entry.start, entry.end
    maintenance = maintenance_for(entry, game)
    if maintenance and entry.type != "maintenance":
        if entry.start_is_deadline and end is None and not entry.open_ended:
            start = last_available_day(start, entry.start_time, maintenance)
        if end is not None and not entry.open_ended:
            adjusted = last_available_day(end, entry.end_time, maintenance)
            # 不整合な期間は原文どおり残し、要確認にする。
            if start is None or adjusted >= start:
                end = adjusted
    return {
        "calendar_start": start.isoformat() if start else None,
        "calendar_end": end.isoformat() if end else None,
    }
