const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = vm.createContext({ Intl, Date, Set, Map, JSON });
const script = fs.readFileSync(path.join(__dirname, "../docs/calendar.js"), "utf8");
vm.runInContext(script.slice(0, script.indexOf("for (const [game, { name }]")), context);

const source = { game: "ongeki", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
const item = (changes) => context.calendarEntry({
  type: "event", title: "「作品A」イベント", subject: "作品A", service: "ongeki", start: "2026-10-01", end: "2026-12-09",
  start_time: null, end_time: null, open_ended: false, songs: [], ...changes,
}, source);
const event = item({});
const challenge = item({ type: "technical_challenge", subject: "作品A ", title: "「作品A」テクニカルチャレンジ" });
const bonus = item({ type: "login_bonus", subject: "『作品A』", end: "2026-10-14", title: "作品A イベント開催記念ログインボーナス" });
const song = item({ type: "song_add", end: null, songs: ["曲A"], subject: "作品A", start: "2026-10-08" });
const genreSong = item({ type: "song_add", end: null, songs: ["曲B"], subject: null });
const other = item({ subject: "作品B", title: "「作品B」イベント" });
const revival = item({ start: "2027-05-01", end: "2027-06-01" });
const revivalQuest = item({ type: "technical_challenge", start: "2027-05-01", end: "2027-06-01" });
const families = context.groupFamilies([event, challenge, bonus, song, genreSong, other, revival, revivalQuest]);
assert.equal(families.length, 2);
assert.deepEqual(Array.from(families[0].members), [event, challenge, bonus, song]);
assert.equal(families[0].title, "「作品A」イベント");
assert.equal(families[0].start, "2026-10-01");
assert.equal(families[0].end, "2026-12-09");
assert.equal(song.family, families[0]);
assert.equal(genreSong.family, undefined);
assert.equal(other.family, undefined);
assert.equal(revival.family, families[1]);
assert.deepEqual(Array.from(context.withFamilies([event, bonus, other]), (entry) => entry.title), ["「作品A」イベント", "「作品B」イベント"]);
assert.equal(context.withFamilies([event])[0], families[0]);

const noEvent = [item({ type: "ranking", subject: "作品C【第2弾】" }), item({ type: "login_bonus", subject: "作品C 第2弾" })];
assert.equal(context.groupFamilies(noEvent)[0].title, "「作品C【第2弾】」");
assert.equal(context.groupFamilies([item({}), item({ type: "event" })]).length, 0);
assert.equal(context.groupFamilies([item({}), item({ type: "quest", service: "chunithm" })]).length, 0);

const collab = item({ subject: "作品D", title: "「作品D」コラボイベント", service: "maimai" });
const area = item({ type: "area_add", subject: "作品D ちほー", title: "作品D ちほー", service: "maimai" });
const otherArea = item({ type: "area_add", subject: "作品Eちほー", title: "作品Eちほー", service: "maimai" });
const areaFamilies = context.groupFamilies([collab, area, otherArea]);
assert.equal(areaFamilies.length, 1);
assert.deepEqual(Array.from(areaFamilies[0].members), [collab, area]);
assert.equal(areaFamilies[0].title, "「作品D」コラボイベント");
assert.equal(otherArea.family, undefined);

// ちほーとその進行で獲得できる楽曲は、ちほーを親にする。楽曲の終了日は親の期間を延ばさない。
const chiho = item({ type: "area_add", subject: "Rotaenoちほー", title: "Rotaenoちほー", service: "maimai", start: "2026-08-21", end: "2026-11-05" });
const chihoSongs = item({ type: "song_unlock", subject: "Rotaenoちほー", service: "maimai", start: "2026-08-21", end: "2026-12-31", songs: ["Manifold Hypothesis", "Inverted World"] });
const collabSongs = item({ type: "song_add", subject: "Rotaeno", service: "maimai", start: "2026-08-21", end: null, songs: ["曲C"] });
const lateSongs = item({ type: "song_add", subject: "Rotaeno", service: "maimai", start: "2026-11-20", end: null, songs: ["曲D"] });
const chihoFamilies = context.groupFamilies([chiho, chihoSongs, collabSongs, lateSongs]);
assert.equal(chihoFamilies.length, 1);
assert.equal(chihoFamilies[0].title, "Rotaenoちほー");
assert.equal(chihoFamilies[0].end, "2026-11-05");
assert.equal(chihoSongs.family, chihoFamilies[0]);
assert.equal(collabSongs.family, chihoFamilies[0]);
assert.equal(lateSongs.family, undefined);
assert.equal(context.withFamilies(context.currentEntries([chiho, chihoSongs], "2026-10-01"))[0], chihoFamilies[0]);
// オトモダチ対戦の報酬譜面は、対戦シーズンを親にする。
const battle = item({ type: "friend_battle", subject: "オトモダチ対戦 シーズン29", title: "オトモダチ対戦 シーズン29", service: "maimai", start: "2026-10-02", end: "2026-10-22" });
const battleChart = item({ type: "standard_chart_add", subject: "オトモダチ対戦 シーズン29", service: "maimai", start: "2026-10-02", end: null, songs: ["曲G"] });
const battleFamilies = context.groupFamilies([battle, battleChart]);
assert.equal(battleFamilies.length, 1);
assert.equal(battleFamilies[0].title, "オトモダチ対戦 シーズン29");
assert.equal(battleChart.family, battleFamilies[0]);
// 楽曲だけ、または期間のある告知のない組み合わせは親にしない。
assert.equal(context.groupFamilies([collabSongs, item({ type: "ultima_add", subject: "Rotaeno", service: "maimai", start: "2026-08-21", end: null, songs: ["曲E"] })]).length, 0);

const data = JSON.parse(fs.readFileSync(path.join(__dirname, "../docs/entries.json"), "utf8"));
const published = context.mergeDuplicates(data.articles.filter((a) => a.status !== "failed")
  .flatMap((article) => article.entries.map((entry) => context.calendarEntry(entry, article.source))));
const found = context.groupFamilies(published);
for (const family of found) {
  assert.ok(new Set(family.members.map((member) => member.type)).size >= 2);
  assert.ok(family.members.every((member) => member.start >= family.start && member.start <= family.end));
  assert.ok(family.members.filter((member) => !context.isSong(member)).every((member) => context.endDate(member) <= family.end));
}
console.log(`Parent event grouping by subject and overlapping periods: passed (${found.length} families in published data)`);

// イベント記事の楽曲と、同じ日の楽曲追加記事に重複する曲は、所属先のある項目に寄せる。
const ongeki = { game: "ongeki", url: "https://example.com/b", title: "楽曲追加記事", date: "2026-09-01" };
const withOrigin = (entry) => ({ ...entry, origins: [{ source: entry.source }] });
const eventSong = withOrigin(item({ type: "song_add", subject: "作品F", start: "2026-09-03", end: null, songs: ["曲X"] }));
const plainSongs = withOrigin(context.calendarEntry({ type: "song_add", title: "楽曲追加", subject: null, service: "ongeki",
  start: "2026-09-03", end: null, open_ended: false, songs: ["曲W", "曲X", "曲Y"] }, ongeki));
const onlyX = withOrigin(context.calendarEntry({ type: "song_add", title: "楽曲追加", subject: null, service: "ongeki",
  start: "2026-09-03", end: null, open_ended: false, songs: ["曲X"] }, ongeki));
const otherDay = withOrigin(context.calendarEntry({ type: "song_add", title: "楽曲追加", subject: null, service: "ongeki",
  start: "2026-09-10", end: null, open_ended: false, songs: ["曲X"] }, ongeki));
const overlapped = context.mergeSongOverlaps([eventSong, plainSongs, otherDay]);
assert.equal(overlapped.length, 3);
assert.deepEqual(Array.from(overlapped[1].songs), ["曲W", "曲Y"]);
assert.deepEqual(Array.from(eventSong.origins, (origin) => origin.source.title), ["記事A", "楽曲追加記事"]);
assert.deepEqual(Array.from(overlapped[2].songs), ["曲X"]);
assert.equal(context.mergeSongOverlaps([withOrigin(eventSong), onlyX]).length, 1);
console.log("Song overlap between event and song articles: passed");
