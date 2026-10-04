const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({ Intl, Date, Set, Map, URL });
const script = fs.readFileSync(path.join(__dirname, "../docs/calendar.js"), "utf8");
vm.runInContext(script.slice(0, script.indexOf("for (const [game, { name }]")), context);
const node = (tag) => ({ tag, dataset: {}, children: [], append(...children) { this.children.push(...children); },
  replaceChildren() { this.children = []; }, showModal() {} });
const content = node("div");
const controls = { "detail-content": content, detail: node("dialog"), search: { value: "" }, type: { value: "" } };
context.document = { createElement: node, getElementById: (id) => controls[id] };
const base = { type: "event", title: "コラボイベント", start: "2026-09-17", end: "2026-11-19",
  start_time: null, end_time: null, open_ended: false, songs: [] };
const sourceA = { game: "maimai", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
const a = context.calendarEntry(base, sourceA);

const goods = context.calendarEntry({ ...base, type: "goods_campaign", title: "グッズ交換キャンペーン" }, sourceA);
context.goodsForTest = [goods, a];
vm.runInContext("entries = goodsForTest", context);
controls.search.value = "";
controls.type.value = "goods_campaign";
assert.equal(context.filteredEntries().length, 1);
assert.equal(context.filteredEntries()[0].title, goods.title);
context.showDetail(goods);
const tags = content.children.find((child) => child.className === "type-tags");
assert.equal(tags.children[0].textContent, "グッズキャンペーン");
assert.equal(tags.children[0].dataset.type, "goods_campaign");
console.log("Goods campaign filtering and display label: passed");
