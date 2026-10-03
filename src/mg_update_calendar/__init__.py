def main(argv: list[str] | None = None) -> int:
    from mg_update_calendar.scraper import main as _main

    return _main(argv)


__all__ = ["main"]
