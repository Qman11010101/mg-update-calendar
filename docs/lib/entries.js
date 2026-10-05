// 抽出結果の読み込み・統合・分類など、DOMに依存しない処理。
import { daysBetween, shortDate, today, validDate } from "./dates.js";

export const games = {
  chunithm: { name: "CHUNITHM", short: "CHU" },
  maimai: { name: "maimai", short: "mai" },
  ongeki: { name: "オンゲキ", short: "ONG" },
};
const types = {
  song_add: "楽曲追加", song_unlock: "楽曲の一般開放・解禁緩和", version_launch: "バージョン稼働",
  goods_campaign: "グッズキャンペーン",
  maintenance: "メンテナンス", service_change: "サービス変更", other: "その他", event: "イベント",
  map_add: "マップ追加・拡張", quest: "クエスト", mission: "ミッション",
  course_add: "認定コース追加", ultima_add: "ULTIMA譜面追加", worlds_end_add: "WORLD’S END譜面追加",
  area_add: "ちほー追加・拡張", friend_battle: "オトモダチ対戦", remaster_add: "Re:MASTER譜面追加",
  dx_chart_add: "でらっくす譜面追加", standard_chart_add: "スタンダード譜面追加", utage_add: "宴譜面追加",
  chapter_add: "チャプター追加", ranking: "ランキング", technical_challenge: "テクニカルチャレンジ",
  gacha: "ガチャ", login_bonus: "ログインボーナス", lunatic_add: "LUNATIC譜面追加",
  avatar_costume: "アバターコスチューム",
};
// 同じ対象名で期間が重なると、1つの親イベントにまとめる種類。稼働などの恒久的な告知は含めない。
const familyTypes = new Set(["event", "quest", "map_add", "area_add", "chapter_add", "ranking",
  "technical_challenge", "login_bonus", "mission", "gacha", "friend_battle"]);
// 楽曲・譜面追加はイベント終了後も残るため、親の期間を決めずに関連楽曲として親に加える。
const songTypes = new Set(["song_add", "song_unlock", "ultima_add", "worlds_end_add", "remaster_add",
  "dx_chart_add", "standard_chart_add", "utage_add", "lunatic_add"]);
const supportedSchemas = [2, 3, 4, 5, 6, 7, 8];

export function typeLabel(type) { return types[type] || type; }
export function endDate(entry) {
  // 終了未定の追加告知は、恒久的なコンテンツを毎日繰り返さないよう開始日の点として扱う。
  return !entry.open_ended && validDate(entry.end) && entry.end >= entry.start ? entry.end : entry.start;
}
export function isRange(entry) { return endDate(entry) > entry.start; }
export function period(entry) {
  if (!entry.start) return "日付不明";
  const start = (entry.official_start ?? entry.start).replaceAll("-", "/") + (entry.start_time ? ` ${entry.start_time}` : "");
  if (entry.open_ended) return `${start}〜（終了日未定）`;
  const end = entry.official_end ?? entry.end;
  return end ? `${start} 〜 ${end.replaceAll("-", "/")}${entry.end_time ? ` ${entry.end_time}` : ""}` : start;
}
// 詳細に出す「最終利用日」。カレンダー上の配置日が正式日時と異なるときだけ返す。
export function lastUsableDay(entry) {
  if (entry.start === entry.official_start && entry.end === entry.official_end) return null;
  return (entry.start_is_deadline ? entry.start : entry.end) || null;
}
export function isSong(entry) { return songTypes.has(entry.type); }
// 詳細に出す曲の表記。アーティスト名が分かるときは「曲名 / アーティスト」にする。
export function songLabel(song) { return song.artist ? `${song.title} / ${song.artist}` : song.title; }
export function itemTypes(item) { return item.members ? item.members.map((member) => member.type) : [item.type]; }

// 関連記事の一覧。http(s)以外のURLはリンクにしない。
export function entrySources(entry) {
  return (entry.origins || [{ source: entry.source }]).map(({ source }) => {
    let url = null;
    try {
      const parsed = new URL(source.url);
      if (["https:", "http:"].includes(parsed.protocol)) url = parsed.href;
    } catch { }
    return { title: source.title, url, date: source.date || "不明" };
  });
}

export function filterEntries(list, { games: selectedGames, type, query }) {
  const normalized = query.normalize("NFKC").toLocaleLowerCase().trim();
  return list.filter((entry) => selectedGames.has(entry.source.game) &&
    (!type || entry.type === type) &&
    (!normalized || [entry.title, ...entry.songs.flatMap((song) => [song.title, song.artist ?? ""]), ...(entry.origins || [{ source: entry.source }]).map((origin) => origin.source.title)].join(" ").normalize("NFKC").toLocaleLowerCase().includes(normalized)));
}
export function byGame(a, b) {
  const order = Object.keys(games);
  return order.indexOf(a.source.game) - order.indexOf(b.source.game);
}
export function byGameAndTitle(a, b) { return byGame(a, b) || a.title.localeCompare(b.title, "ja"); }

export function currentEntries(list, referenceDate = today) {
  return list.filter((entry) => entry.start && isRange(entry) &&
    entry.start <= referenceDate && endDate(entry) >= referenceDate);
}
// 今後の一覧では、まだ始まっていない親イベントは親1件に、開催中の親に後から加わる告知は単独で並べる。
export function upcomingEntries(list, referenceDate = today) {
  const upcoming = list.filter((entry) => entry.start && entry.start > referenceDate)
    .map((entry) => entry.family && entry.family.start > referenceDate ? entry.family : entry);
  return [...new Set(upcoming)];
}
// 開催中は終了の近い順、今後は開始の近い順に並べる。
export function nowLists(list, referenceDate = today) {
  return {
    current: currentEntries(withFamilies(currentEntries(list, referenceDate)), referenceDate)
      .sort((a, b) => endDate(a).localeCompare(endDate(b)) || byGame(a, b)),
    upcoming: upcomingEntries(list, referenceDate).sort((a, b) => a.start.localeCompare(b.start) || byGame(a, b)),
  };
}
// 日別パネルの区分。各区分の項目は note で添え書きを付ける。
export function dayGroups(dated, day) {
  return [
    {
      label: "この日から", entries: dated.filter((entry) => entry.start === day),
      note: (entry) => isRange(entry) ? `${shortDate(endDate(entry))}まで` : entry.open_ended ? "終了日未定" : entry.start_time,
    },
    {
      label: "この日まで", entries: dated.filter((entry) => isRange(entry) && endDate(entry) === day),
      note: (entry) => `${shortDate(entry.start)}から・最終日${entry.end_time ? ` ${entry.end_time}` : ""}`,
    },
    {
      label: "開催中", entries: dated.filter((entry) => isRange(entry) && entry.start < day && endDate(entry) > day),
      note: (entry) => `残り${daysBetween(day, endDate(entry))}日`,
    },
  ].map((group) => ({ ...group, entries: group.entries.sort(byGameAndTitle) }));
}

export function subjectKey(subject) {
  return (subject || "").normalize("NFKC").replace(/[\s「」『』【】]/g, "") || null;
}
// マップ・ちほー・チャプターの対象名は「作品Aちほー」のように種類の語が付くため、語を除いて同じ作品のイベントとまとめる。
const contentWords = { map_add: "マップ", area_add: "ちほー", chapter_add: "チャプター" };
function familyKey(entry) {
  const key = subjectKey(entry.subject);
  // 楽曲の対象名は所属先と同じ表記なので、所属先がマップ・ちほー・チャプターでも同じ語を除く。
  const words = songTypes.has(entry.type) ? Object.values(contentWords) : [contentWords[entry.type]];
  const word = key && words.find((item) => item && key.endsWith(item) && key.length > item.length);
  return word ? key.slice(0, -word.length) : key;
}
// 親イベントを作り、各メンバーの entry.family に設定する。前回の設定は呼び出し側で消しておく。
export function groupFamilies(list) {
  const buckets = new Map();
  for (const entry of list) {
    const key = familyKey(entry);
    if (!key || !(familyTypes.has(entry.type) || isSong(entry)) || !entry.start) continue;
    const bucket = JSON.stringify([entry.source.game, entry.service ?? null, key]);
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    buckets.get(bucket).push(entry);
  }
  const families = [];
  for (const members of buckets.values()) {
    members.sort((a, b) => a.start.localeCompare(b.start) || isSong(a) - isSong(b) || endDate(b).localeCompare(endDate(a)));
    // 同じ名前の復刻などを別の親にするため、期間が連続して重なる告知と、その期間中に始まる楽曲だけをまとめる。
    let cluster = [];
    const clusterEnd = () => cluster.filter((entry) => !isSong(entry)).map(endDate).sort().at(-1);
    const flush = () => {
      const contents = cluster.filter((entry) => !isSong(entry));
      if (new Set(cluster.map((entry) => entry.type)).size >= 2 && contents.some(isRange)) {
        const event = contents.find((entry) => entry.type === "event");
        const subject = contents[0].subject.trim().replaceAll("『", "「").replaceAll("』", "」");
        const family = {
          title: event ? event.title : contents.length === 1 ? contents[0].title : `「${subject.replace(/^「([^「」]*)」$/, "$1")}」`,
          source: contents[0].source, service: contents[0].service, members: cluster, songs: [],
          start: contents[0].start, end: clusterEnd(), open_ended: false,
        };
        cluster.forEach((entry) => { entry.family = family; });
        families.push(family);
      }
      cluster = [];
    };
    for (const entry of members) {
      const end = clusterEnd();
      // 期間のある告知より前に始まる楽曲は、その告知に属さないものとして切り離す。
      if (cluster.length && (!end || entry.start > end)) flush();
      cluster.push(entry);
    }
    flush();
  }
  return families;
}
// 開催中の一覧では、親イベントにまとまる告知を親1件に置き換える。
export function withFamilies(list) {
  return [...new Set(list.map((entry) => entry.family || entry))];
}

export function calendarEntry(entry, source) {
  return {
    ...entry, official_start: entry.start, official_end: entry.end,
    start: validDate(entry.calendar_start) ? entry.calendar_start : validDate(entry.start) ? entry.start : null,
    end: validDate(entry.calendar_end) ? entry.calendar_end : entry.end,
    // 版7までは曲名だけの文字列で持つ。
    songs: (entry.songs || []).map((song) => typeof song === "string" ? { title: song, artist: null } : song),
    source,
  };
}
export function mergeDuplicates(list) {
  const matches = new Map();
  const merged = [];
  for (const entry of list) {
    const item = {
      ...entry, origins: [{
        source: entry.source, date_text: entry.date_text,
        evidence: entry.evidence, confidence: entry.confidence
      }]
    };
    // 日時や対象曲の違いは、同名の別告知や日程変更の可能性があるため残す。
    const key = JSON.stringify([entry.source.game, entry.service ?? null, entry.type, entry.title,
    entry.official_start, entry.start_time ?? null, entry.official_end ?? null, entry.end_time ?? null,
    entry.start, entry.end ?? null, entry.open_ended, entry.start_is_deadline ?? false,
    [...new Set(entry.songs.map((song) => song.title))].sort()]);
    if (!validDate(entry.official_start) || !entry.title || !entry.type) {
      merged.push(item);
    } else if (matches.has(key)) {
      matches.get(key).origins.push(...item.origins);
    } else {
      matches.set(key, item);
      merged.push(item);
    }
  }
  return merged;
}
// 同じ曲の追加が、イベント記事（所属先あり）と楽曲追加の記事（所属先なし）の両方に載ることがある。
// 同じ日・同じ種類なら所属先のある項目に曲を寄せ、所属先のない項目からはその曲を除く。曲が残らなければ出典だけ移して消す。
export function mergeSongOverlaps(list) {
  const key = (entry) => JSON.stringify([entry.source.game, entry.service ?? null, entry.type, entry.start]);
  const linked = list.filter((entry) => isSong(entry) && entry.start && subjectKey(entry.subject));
  return list.flatMap((entry) => {
    if (!isSong(entry) || !entry.start || subjectKey(entry.subject)) return [entry];
    const titles = (item) => item.songs.map((song) => song.title);
    const targets = linked.filter((item) => key(item) === key(entry) && titles(item).some((title) => titles(entry).includes(title)));
    if (!targets.length) return [entry];
    targets.forEach((target) => target.origins.push(...entry.origins));
    const songs = entry.songs.filter((song) => !targets.some((target) => titles(target).includes(song.title)));
    return songs.length ? [{ ...entry, songs }] : [];
  });
}
// entries.json の内容を表示用の項目一覧にする。対応していない形式なら例外を投げる。
export function buildEntries(data) {
  if (!supportedSchemas.includes(data.schema_version) || data.mode !== "extraction" || !Array.isArray(data.articles)) throw new Error("Unsupported data");
  const extracted = data.articles.filter((article) => article.status !== "failed" && games[article.source.game])
    .flatMap((article) => article.entries.map((entry) => calendarEntry(entry, article.source)));
  return mergeSongOverlaps(mergeDuplicates(extracted));
}
