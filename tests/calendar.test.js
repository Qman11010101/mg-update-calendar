import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { formatDateTime, monthRange, shiftMonth } from "../docs/lib/dates.js";
import {
  buildEntries, calendarEntry, currentEntries, dayGroups, endDate, entrySources, filterEntries, games, isRange,
  lastUsableDay, mergeDuplicates, nowLists, period, siteData, upcomingEntries,
} from "../docs/lib/entries.js";

const document = JSON.parse(readFileSync(new URL("../docs/entries.json", import.meta.url), "utf8"));
const allGames = new Set(Object.keys(games));
const base = {
  type: "event", title: "「超かぐや姫！」コラボイベント", start: "2026-09-17", end: "2026-11-19",
  start_time: null, end_time: null, open_ended: false, songs: [], evidence: "原文A", date_text: "9/17〜11/19",
};
const sourceA = { game: "maimai", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
const sourceB = { ...sourceA, url: "https://example.com/b", title: "記事B" };
const a = calendarEntry(base, sourceA);
const b = calendarEntry({ ...base, evidence: "原文B" }, sourceB);
const merged = mergeDuplicates([a, b]);

test("Calendar date placement and original timestamps", () => {
  const article = document.articles.find((a) => a.source.url === "https://info-maimai.sega.jp/9772/");
  const raw = article.entries.find((e) => e.service === "card_maker");
  assert.ok(raw);
  const item = calendarEntry(raw, article.source);
  assert.equal(item.start, "2026-09-01");
  assert.equal(item.official_start, "2026-09-02");
  assert.equal(period(item), "2026/09/02 01:59");
  assert.equal(item.source.game, "maimai");
  assert.equal(lastUsableDay(item), "2026-09-01");

  const legacy = { start: "2026-09-01", end: null, open_ended: false, start_time: "07:00" };
  assert.equal(calendarEntry(legacy, {}).start, legacy.start);
  assert.equal(period(calendarEntry(legacy, {})), "2026/09/01 07:00");
  assert.equal(lastUsableDay(calendarEntry(legacy, {})), null);
  const range = calendarEntry({
    ...legacy, end: "2026-09-03", end_time: "03:59",
    calendar_start: "2026-09-01", calendar_end: "2026-09-02",
  }, {});
  assert.equal(endDate(range), "2026-09-02");
  assert.equal(period(range), "2026/09/01 07:00 〜 2026/09/03 03:59");
  assert.equal(lastUsableDay(range), "2026-09-02");
  const single = calendarEntry({ ...legacy, end: "2026-09-02", calendar_end: "2026-09-01" }, {});
  assert.equal(isRange(single), false);
});

test("Site data keeps only what the calendar displays", () => {
  const site = siteData(document);
  assert.equal(site.updated_at, document.updated_at);
  assert.ok(site.articles.every((article) => article.entries.every((entry) => !("evidence" in entry) && !("date_text" in entry))));
  const full = buildEntries(document);
  const compact = buildEntries(site);
  assert.equal(compact.length, full.length);
  compact.forEach((entry, index) => {
    for (const [key, value] of Object.entries(entry)) assert.deepEqual(value, full[index][key], key);
  });
  assert.throws(() => siteData({ ...document, schema_version: 1 }));
});

test("Duplicate merging, source links, search and exclusion cases", () => {
  assert.equal(merged.length, 1);
  assert.equal(merged[0].origins.length, 2);
  assert.deepEqual(merged[0].origins[1], { source: sourceB });
  assert.equal(a.origins, undefined);
  for (const change of [
    { title: "「別作品」コラボイベント" }, { type: "area_add" }, { start: "2026-09-18" },
    { end: "2026-11-20" }, { start_time: "10:00" }, { service: "card_maker" },
    { open_ended: true }, { start_is_deadline: true }, { songs: ["別の曲"] },
    { calendar_end: "2026-11-18" },
  ]) {
    assert.equal(mergeDuplicates([a, calendarEntry({ ...base, ...change }, sourceB)]).length, 2);
  }
  assert.equal(mergeDuplicates([a, calendarEntry(base, { ...sourceB, game: "ongeki" })]).length, 2);
  assert.equal(mergeDuplicates([
    calendarEntry({ ...base, start: null }, sourceA),
    calendarEntry({ ...base, start: null }, sourceB),
  ]).length, 2);
  assert.equal(mergeDuplicates([
    calendarEntry({ ...base, songs: ["曲A", "曲B"] }, sourceA),
    calendarEntry({ ...base, songs: ["曲B", "曲A"] }, sourceB),
  ]).length, 1);
  const extracted = document.articles.filter((a) => a.status !== "failed")
    .flatMap((article) => article.entries.map((entry) => calendarEntry(entry, article.source)));
  const combined = mergeDuplicates(extracted);
  assert.equal(combined.reduce((count, entry) => count + entry.origins.length, 0), extracted.length);
  const preservedSources = combined.flatMap((entry) => entry.origins.map((origin) => origin.source.url)).sort();
  assert.deepEqual(preservedSources, extracted.map((entry) => entry.source.url).sort());
  const fixtureEntries = ["コラボA", "コラボB"].flatMap((title) => [
    calendarEntry({ ...base, title }, sourceA),
    calendarEntry({ ...base, title }, sourceB),
  ]);
  const fixtureCombined = mergeDuplicates(fixtureEntries);
  assert.equal(fixtureCombined.length, 2);
  for (const entry of fixtureCombined) {
    assert.deepEqual(entry.origins.map((origin) => origin.source.url), [sourceA.url, sourceB.url]);
  }

  const sources = entrySources(merged[0]);
  assert.equal(sources.length, 2);
  assert.equal(sources[1].url, sourceB.url);
  assert.deepEqual(entrySources(calendarEntry(base, { ...sourceA, url: "javascript:alert(1)", date: null })),
    [{ title: "記事A", url: null, date: "不明" }]);
  assert.equal(filterEntries(merged, { games: allGames, type: "", query: "記事B" }).length, 1);
  assert.equal(filterEntries(merged, { games: allGames, type: "", query: "記事C" }).length, 0);
  assert.equal(filterEntries(merged, { games: new Set(["ongeki"]), type: "", query: "" }).length, 0);
});

test("Independent entries, own periods, and legacy relationship metadata ignored", () => {
  const eventItem = (changes = {}) => calendarEntry({ ...base, service: "maimai", ...changes }, sourceA);
  const event = eventItem({ event_id: "evt_family", event_parent_id: "evt_family", title: "Event" });
  const bonus = eventItem({ event_parent_id: "evt_family", type: "login_bonus", end: "2026-09-30", title: "Bonus" });
  const song = eventItem({ event_parent_id: "evt_family", type: "song_add", end: null, title: "Song", songs: ["A"] });
  const challenge = eventItem({ event_id: "evt_family", event_parent_id: "evt_family", type: "technical_challenge", title: "Challenge" });
  const family = [event, bonus, song, challenge];
  assert.deepEqual(currentEntries(family, "2026-10-04"), [event, challenge]);
  assert.equal(currentEntries([bonus], "2026-10-04").length, 0);
  assert.equal(currentEntries([song], "2026-10-04").length, 0);
  assert.equal(currentEntries(family, "2026-12-01").length, 0);
  assert.equal(currentEntries([bonus], "2026-09-30").length, 1);
  assert.equal(currentEntries([eventItem({ start: null })], "2026-10-04").length, 0);
  assert.equal(mergeDuplicates([eventItem({ event_id: "old_a" }), eventItem({ event_id: "old_b" })]).length, 1);
  assert.equal(bonus.family, undefined);
});

test("Upcoming list keeps late members of ongoing families and collapses future families", () => {
  const later = { ...a, start: "2026-10-10", end: "2026-10-20" };
  const ongoingFamily = { start: "2026-10-01" };
  const futureFamily = { start: "2026-10-08" };
  const lateSong = { ...a, type: "song_add", start: "2026-10-12", end: null, family: ongoingFamily };
  const futureMember = { ...a, start: "2026-10-08", family: futureFamily };
  const futureSibling = { ...a, start: "2026-10-09", family: futureFamily };
  const upcoming = upcomingEntries([a, later, lateSong, futureMember, futureSibling], "2026-10-05");
  assert.deepEqual(upcoming, [later, lateSong, futureFamily]);
});

test("Now lists sort current by end date and upcoming by start date", () => {
  const ending = { ...a, end: "2026-10-10" };
  const ongeki = calendarEntry(base, { ...sourceA, game: "ongeki" });
  const soon = { ...a, start: "2026-10-20", end: "2026-10-30" };
  const sooner = { ...a, start: "2026-10-07", end: null };
  const { current, upcoming } = nowLists([ongeki, a, ending, soon, sooner], "2026-10-05");
  assert.deepEqual(current, [ending, a, ongeki]);
  assert.deepEqual(upcoming, [sooner, soon]);
});

test("Day panel groups entries by starting, ending and ongoing", () => {
  const starting = { ...a, start: "2026-10-05", end: null };
  const ending = { ...a, start: "2026-10-01", end: "2026-10-05" };
  const groups = dayGroups([a, starting, ending], "2026-10-05");
  assert.deepEqual(groups.map((group) => group.label), ["この日から", "この日まで", "開催中"]);
  assert.deepEqual(groups.map((group) => group.entries), [[starting], [ending], [a]]);
  assert.equal(groups[1].note(ending), "10/1から・最終日");
  assert.equal(groups[2].note(a), "残り45日");
});

test("Month helpers and data loading", () => {
  assert.deepEqual(monthRange("2028-02"), { first: "2028-02-01", last: "2028-02-29" });
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
  assert.equal(shiftMonth("2026-01", -1), "2025-12");
  assert.ok(buildEntries(document).length > 0);
  assert.throws(() => buildEntries({ ...document, schema_version: 1 }), /Unsupported data/);
});

test("最終更新日時を日本時間で表示し、読めない値は表示しない", () => {
  assert.equal(formatDateTime("2026-10-05T15:30:00+00:00"), "2026/10/06 00:30");
  assert.equal(formatDateTime(null), null);
  assert.equal(formatDateTime("不明"), null);
});
