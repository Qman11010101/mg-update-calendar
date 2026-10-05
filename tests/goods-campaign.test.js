import assert from "node:assert/strict";
import { test } from "node:test";
import { calendarEntry, filterEntries, games, typeLabel } from "../docs/lib/entries.js";

test("Goods campaign filtering and display label", () => {
  const base = { type: "event", title: "コラボイベント", start: "2026-09-17", end: "2026-11-19",
    start_time: null, end_time: null, open_ended: false, songs: [] };
  const sourceA = { game: "maimai", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
  const a = calendarEntry(base, sourceA);
  const goods = calendarEntry({ ...base, type: "goods_campaign", title: "グッズ交換キャンペーン" }, sourceA);
  const filtered = filterEntries([goods, a], { games: new Set(Object.keys(games)), type: "goods_campaign", query: "" });
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].title, goods.title);
  assert.equal(typeLabel("goods_campaign"), "グッズキャンペーン");
  assert.equal(typeLabel("unknown_type"), "unknown_type");
});
