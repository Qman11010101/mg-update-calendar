const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = vm.createContext({ Intl, Date, Set, Map });
const script = fs.readFileSync(path.join(__dirname, "../docs/calendar.js"), "utf8");
vm.runInContext(script.slice(0, script.indexOf("for (const [game, { name }]")), context);
const document = JSON.parse(fs.readFileSync(path.join(__dirname, "../docs/entries.json"), "utf8"));
const article = document.articles.find((a) => a.source.url === "https://info-maimai.sega.jp/9772/");
const raw = article.entries.find((e) => e.service === "card_maker");
assert.ok(raw);
const item = context.calendarEntry(raw, article.source);
assert.equal(item.start, "2026-09-01");
assert.equal(item.official_start, "2026-09-02");
assert.equal(context.period(item), "2026/09/02 01:59");
assert.equal(item.source.game, "maimai");

const legacy = { start: "2026-09-01", end: null, open_ended: false, start_time: "07:00" };
assert.equal(context.calendarEntry(legacy, {}).start, legacy.start);
assert.equal(context.period(context.calendarEntry(legacy, {})), "2026/09/01 07:00");
const range = context.calendarEntry({
  ...legacy, end: "2026-09-03", end_time: "03:59",
  calendar_start: "2026-09-01", calendar_end: "2026-09-02",
}, {});
assert.equal(context.endDate(range), "2026-09-02");
assert.equal(context.period(range), "2026/09/01 07:00 〜 2026/09/03 03:59");
const single = context.calendarEntry({ ...legacy, end: "2026-09-02", calendar_end: "2026-09-01" }, {});
assert.equal(context.isRange(single), false);
console.log("Calendar date placement and original timestamps: passed");

const base = {
  type: "event", title: "「超かぐや姫！」コラボイベント", start: "2026-09-17", end: "2026-11-19",
  start_time: null, end_time: null, open_ended: false, songs: [], evidence: "原文A", date_text: "9/17〜11/19",
};
const sourceA = { game: "maimai", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
const sourceB = { ...sourceA, url: "https://example.com/b", title: "記事B" };
const a = context.calendarEntry(base, sourceA);
const b = context.calendarEntry({ ...base, evidence: "原文B" }, sourceB);
const merged = context.mergeDuplicates([a, b]);
assert.equal(merged.length, 1);
assert.equal(merged[0].origins.length, 2);
assert.equal(merged[0].origins[1].evidence, "原文B");
assert.equal(a.origins, undefined);
for (const change of [
  { title: "「別作品」コラボイベント" }, { type: "area_add" }, { start: "2026-09-18" },
  { end: "2026-11-20" }, { start_time: "10:00" }, { service: "card_maker" },
  { open_ended: true }, { start_is_deadline: true }, { songs: ["別の曲"] },
  { calendar_end: "2026-11-18" },
]) {
  assert.equal(context.mergeDuplicates([a, context.calendarEntry({ ...base, ...change }, sourceB)]).length, 2);
}
assert.equal(context.mergeDuplicates([a, context.calendarEntry(base, { ...sourceB, game: "ongeki" })]).length, 2);
assert.equal(context.mergeDuplicates([
  context.calendarEntry({ ...base, start: null }, sourceA),
  context.calendarEntry({ ...base, start: null }, sourceB),
]).length, 2);
assert.equal(context.mergeDuplicates([
  context.calendarEntry({ ...base, songs: ["曲A", "曲B"] }, sourceA),
  context.calendarEntry({ ...base, songs: ["曲B", "曲A"] }, sourceB),
]).length, 1);
const extracted = document.articles.filter((a) => a.status !== "failed")
  .flatMap((article) => article.entries.map((entry) => context.calendarEntry(entry, article.source)));
const combined = context.mergeDuplicates(extracted);
assert.equal(combined.reduce((count, entry) => count + entry.origins.length, 0), extracted.length);
const preservedSources = combined.flatMap((entry) => entry.origins.map((origin) => origin.source.url)).sort();
assert.deepEqual(Array.from(preservedSources), extracted.map((entry) => entry.source.url).sort());
const fixtureEntries = ["コラボA", "コラボB"].flatMap((title) => [
  context.calendarEntry({ ...base, title }, sourceA),
  context.calendarEntry({ ...base, title }, sourceB),
]);
const fixtureCombined = context.mergeDuplicates(fixtureEntries);
assert.equal(fixtureCombined.length, 2);
for (const entry of fixtureCombined) {
  assert.deepEqual(Array.from(entry.origins, (origin) => origin.source.url), [sourceA.url, sourceB.url]);
}
const node = (tag) => ({ tag, dataset: {}, children: [], append(...children) { this.children.push(...children); },
  replaceChildren() { this.children = []; }, showModal() {}, addEventListener() {} });
const content = node("div");
const controls = { "detail-content": content, detail: node("dialog"), search: { value: "記事B" }, type: { value: "" } };
context.document = { createElement: node, getElementById: (id) => controls[id] };
context.URL = URL;
context.showDetail(merged[0]);
const links = content.children.flatMap((child) => child.children || []).filter((child) => child.tag === "a");
assert.equal(links.length, 2);
assert.equal(links[1].href, sourceB.url);
context.mergedForTest = merged;
vm.runInContext("entries = mergedForTest", context);
assert.equal(context.filteredEntries().length, 1);
console.log(`Duplicate merging, source links, search and exclusion cases: passed (${extracted.length - combined.length} duplicates in published data)`);


const eventItem = (changes = {}) => context.calendarEntry({ ...base, service: "maimai", ...changes }, sourceA);
const event = eventItem({ event_id: "evt_family", event_parent_id: "evt_family", title: "Event" });
const bonus = eventItem({ event_parent_id: "evt_family", type: "login_bonus", end: "2026-09-30", title: "Bonus" });
const song = eventItem({ event_parent_id: "evt_family", type: "song_add", end: null, title: "Song", songs: ["A"] });
const challenge = eventItem({ event_id: "evt_family", event_parent_id: "evt_family", type: "technical_challenge", title: "Challenge" });
const family = [event, bonus, song, challenge];
const current = context.currentEntries(family, "2026-10-04");
assert.deepEqual(Array.from(current), [event, challenge]);
assert.equal(context.currentEntries([bonus], "2026-10-04").length, 0);
assert.equal(context.currentEntries([song], "2026-10-04").length, 0);
assert.equal(context.currentEntries(family, "2026-12-01").length, 0);
assert.equal(context.currentEntries([bonus], "2026-09-30").length, 1);
assert.equal(context.currentEntries([eventItem({ start: null })], "2026-10-04").length, 0);
assert.equal(context.mergeDuplicates([eventItem({ event_id: "old_a" }), eventItem({ event_id: "old_b" })]).length, 1);
context.showDetail(bonus);
assert.ok(!content.children.some((child) => child.textContent?.startsWith("親イベント：")));
assert.equal(content.children.find((child) => child.tag === "h2").textContent, "Bonus");
console.log("Independent entries, own periods, and legacy relationship metadata ignored: passed");

const later = { ...a, start: "2026-10-10", end: "2026-10-20" };
const ongoingFamily = { start: "2026-10-01" };
const futureFamily = { start: "2026-10-08" };
const lateSong = { ...a, type: "song_add", start: "2026-10-12", end: null, family: ongoingFamily };
const futureMember = { ...a, start: "2026-10-08", family: futureFamily };
const futureSibling = { ...a, start: "2026-10-09", family: futureFamily };
const upcoming = context.upcomingEntries([a, later, lateSong, futureMember, futureSibling], "2026-10-05");
assert.deepEqual([...upcoming], [later, lateSong, futureFamily]);
console.log("Upcoming list keeps late members of ongoing families and collapses future families: passed");
