import assert from "node:assert/strict";
import { test } from "node:test";
import { addMonths } from "../docs/lib/dates.js";
import { calendarEntry, groupFamilies, keepUntil, pruneData } from "../docs/lib/entries.js";

const source = { game: "ongeki", url: "https://example.com/a", title: "記事A", date: "2026-09-01" };
const raw = (changes) => ({
  type: "event", title: "「作品A」イベント", subject: "作品A", service: "ongeki", start: "2026-10-01", end: "2026-12-09",
  start_time: null, end_time: null, open_ended: false, songs: [], ...changes,
});
const item = (changes, from = source) => calendarEntry(raw(changes), from);

test("Adding months clamps to the end of month", () => {
  assert.equal(addMonths("2026-07-02", 3), "2026-10-02");
  assert.equal(addMonths("2026-11-30", 3), "2027-02-28");
  assert.equal(addMonths("2027-12-31", 2), "2028-02-29");
});

test("How long each entry is kept", () => {
  // 親イベントのメンバーは、点の楽曲も先に終わるログインボーナスも親の終了日まで残す。期間が親より長いメンバーは自身の終了日まで。
  const event = item({});
  const bonus = item({ type: "login_bonus", end: "2026-10-14" });
  const song = item({ type: "song_add", end: null, songs: ["曲A"], start: "2026-10-08" });
  const unlock = item({ type: "song_unlock", end: "2027-01-31", songs: ["曲B"] });
  groupFamilies([event, bonus, song, unlock]);
  assert.equal(keepUntil(event), "2026-12-09");
  assert.equal(keepUntil(bonus), "2026-12-09");
  assert.equal(keepUntil(song), "2026-12-09");
  assert.equal(keepUntil(unlock), "2027-01-31");

  // 親に紐づかない点（終了日未定を含む）は開始日から3か月、期間は終了日、日付不明は記事の公開日から3か月。
  assert.equal(keepUntil(item({ type: "song_add", subject: null, end: null, songs: ["曲C"] })), "2027-01-01");
  assert.equal(keepUntil(item({ type: "version_launch", subject: "Re:Fresh", end: null, open_ended: true })), "2027-01-01");
  assert.equal(keepUntil(item({ subject: "作品B" })), "2026-12-09");
  assert.equal(keepUntil(item({ subject: "作品B", start: null, end: null })), "2026-12-01");
  assert.equal(keepUntil(item({ subject: "作品B", start: null, end: null }, { ...source, date: null })), null);

  // 終了日のない親（常設マップと同じ日の楽曲）は、メンバーの点としての最終日まで残す。
  const map = item({ type: "map_add", subject: "作品Cマップ", end: null });
  const mapSong = item({ type: "song_add", subject: "作品Cマップ", end: null, songs: ["曲D"] });
  groupFamilies([map, mapSong]);
  assert.ok(map.family);
  assert.equal(keepUntil(map), "2027-01-01");
  assert.equal(keepUntil(mapSong), "2027-01-01");
});

test("Pruning finished entries and articles", () => {
  const article = (url, date, entries) => ({ source: { ...source, url, date }, status: "extracted", content_hash: url, entries });
  const data = {
    schema_version: 8, mode: "extraction", updated_at: "2026-10-01T00:00:00+00:00",
    articles: [
      // イベントの記事。楽曲は親の終了日（12/9）まで残る。
      article("event", "2026-09-20", [raw({}), raw({ type: "song_add", end: null, songs: ["曲A"] })]),
      // 単独の楽曲追加は10/1から3か月（2027/1/1）まで、期間の終わったミッションは終了日まで。
      article("mixed", "2026-09-20", [raw({ type: "song_add", subject: null, end: null, songs: ["曲B"] }),
        raw({ type: "mission", subject: "9月度", start: "2026-09-01", end: "2026-09-30" })]),
      // エントリのない記事は公開日から3か月残す。
      article("empty", "2026-09-20", []),
      article("failed", "2026-05-01", []),
    ],
  };
  const keep = (result) => result.data.articles.map((a) => `${a.source.url}:${a.entries.length}`);

  const october = pruneData(data, "2026-10-09");
  assert.deepEqual(keep(october), ["event:2", "mixed:1", "empty:0"]);
  assert.deepEqual(october.removed, ["failed"]);
  assert.equal(october.entryCount, 1);
  assert.equal(october.data.articles[0], data.articles[0]);
  assert.equal(october.data.updated_at, data.updated_at);
  assert.equal(data.articles[1].entries.length, 2);

  assert.deepEqual(keep(pruneData(data, "2026-12-09")), ["event:2", "mixed:1", "empty:0"]);
  // 記事のエントリがなくなっても、公開日から3か月（12/20）までは記事を残し、新着として抽出し直さないようにする。
  const december = pruneData(data, "2026-12-10");
  assert.deepEqual(keep(december), ["event:0", "mixed:1", "empty:0"]);
  assert.deepEqual(pruneData(data, "2027-01-02").removed, ["event", "mixed", "empty", "failed"]);
});
