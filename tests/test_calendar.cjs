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


const eventItem = (event_id, changes = {}, source = sourceA) => context.calendarEntry(
  { ...base, service: "maimai", event_id, ...changes }, source);
const separated = context.periodGroups([
  eventItem("evt_kaguya"), eventItem("evt_kaguya", { type: "area_add", title: "超かぐや姫！ちほー" }, sourceB),
  eventItem("evt_hiroshi", { title: "野原ひろし コラボイベント" }),
  eventItem("evt_hiroshi", { type: "area_add", title: "野原ひろし ちほー" }),
]);
assert.equal(separated.length, 2);
assert.deepEqual(Array.from(separated, (group) => group.entries.length), [2, 2]);
assert.equal(context.periodGroups([a, b]).length, 2);
assert.equal(context.periodGroups([eventItem(null), eventItem(""), eventItem(" ")]).length, 3);
for (const changes of [{ service: "card_maker" }, { start: "2026-09-18" }, { end: "2026-11-20" }]) {
  assert.equal(context.periodGroups([eventItem("evt_a"), eventItem("evt_a", changes)]).length, 2);
}
assert.equal(context.periodGroups([eventItem("evt_a"), eventItem("evt_a", {}, { ...sourceA, game: "ongeki" })]).length, 2);
assert.equal(context.mergeDuplicates([eventItem("evt_a"), eventItem("evt_b")]).length, 2);
context.showGroup(separated[0]);
assert.ok(content.children.some((child) => child.textContent === "このイベントの関連項目"));
console.log("Explicit event grouping, legacy isolation and source preservation: passed");
