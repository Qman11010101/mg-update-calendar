"use strict";

const games = {
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
const weekdayNames = ["日", "月", "火", "水", "木", "金", "土"];
const $ = (id) => document.getElementById(id);
const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date());
let month = today.slice(0, 7);
let selected = today;
let entries = [];
let dated = [];
let nowExpanded = false;
let nowView = "current";
const nowLimit = 8;
const selectedGames = new Set(Object.keys(games));
let holidays = new Set();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function dateKey(date) { return date.toISOString().slice(0, 10); }
function parseDate(value) { return new Date(`${value}T00:00:00Z`); }
// 祝日は日曜と同じ見た目で扱う。
function weekdayClass(key, weekday) {
  return weekday === 0 || holidays.has(key) ? " sunday" : weekday === 6 ? " saturday" : "";
}
function offsetDate(value, days) {
  const date = parseDate(value);
  date.setUTCDate(date.getUTCDate() + days);
  return dateKey(date);
}
function daysBetween(from, to) { return Math.round((parseDate(to) - parseDate(from)) / 86400000); }
function shortDate(value) { return `${Number(value.slice(5, 7))}/${Number(value.slice(8))}`; }
function validDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(parseDate(value).valueOf()) && dateKey(parseDate(value)) === value;
}
function endDate(entry) {
  // 終了未定の追加告知は、恒久的なコンテンツを毎日繰り返さないよう開始日の点として扱う。
  return !entry.open_ended && validDate(entry.end) && entry.end >= entry.start ? entry.end : entry.start;
}
function isRange(entry) { return endDate(entry) > entry.start; }
function period(entry) {
  if (!entry.start) return "日付不明";
  const start = (entry.official_start ?? entry.start).replaceAll("-", "/") + (entry.start_time ? ` ${entry.start_time}` : "");
  if (entry.open_ended) return `${start}〜（終了日未定）`;
  const end = entry.official_end ?? entry.end;
  return end ? `${start} 〜 ${end.replaceAll("-", "/")}${entry.end_time ? ` ${entry.end_time}` : ""}` : start;
}
function filteredEntries() {
  const query = $("search").value.normalize("NFKC").toLocaleLowerCase().trim();
  return entries.filter((entry) => selectedGames.has(entry.source.game) &&
    (!$("type").value || entry.type === $("type").value) &&
    (!query || [entry.title, ...entry.songs, ...(entry.origins || [{ source: entry.source }]).map((origin) => origin.source.title)].join(" ").normalize("NFKC").toLocaleLowerCase().includes(query)));
}
function byGameAndTitle(a, b) {
  const order = Object.keys(games);
  return order.indexOf(a.source.game) - order.indexOf(b.source.game) || a.title.localeCompare(b.title, "ja");
}
function currentEntries(list, referenceDate = today) {
  return list.filter((entry) => entry.start && isRange(entry) &&
    entry.start <= referenceDate && endDate(entry) >= referenceDate);
}
// 今後の一覧では、まだ始まっていない親イベントは親1件に、開催中の親に後から加わる告知は単独で並べる。
function upcomingEntries(list, referenceDate = today) {
  const upcoming = list.filter((entry) => entry.start && entry.start > referenceDate)
    .map((entry) => entry.family && entry.family.start > referenceDate ? entry.family : entry);
  return [...new Set(upcoming)];
}
function subjectKey(subject) {
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
function isSong(entry) { return songTypes.has(entry.type); }
function groupFamilies(list) {
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
function itemTypes(item) { return item.members ? item.members.map((member) => member.type) : [item.type]; }
function openItem(item) { return item.members ? showFamily(item) : showDetail(item); }
// 開催中の一覧では、親イベントにまとまる告知を親1件に置き換える。
function withFamilies(list) {
  return [...new Set(list.map((entry) => entry.family || entry))];
}
function typeTags(entryTypes) {
  const tags = element("span", "type-tags");
  for (const type of new Set(entryTypes)) {
    const tag = element("span", "type-tag", types[type] || type);
    tag.dataset.type = type;
    tags.append(tag);
  }
  return tags;
}
function listItem(entry, note, onClick = () => openItem(entry)) {
  const button = element("button", `item ${entry.source.game}`);
  button.type = "button";
  button.append(element("span", "item-game", games[entry.source.game].short));
  const body = element("span", "item-body");
  body.append(element("span", "item-title", entry.title));
  const meta = typeTags(itemTypes(entry));
  if (note) meta.append(element("span", "item-meta", note));
  body.append(meta);
  button.append(body);
  button.title = `${games[entry.source.game].name}｜${entry.title}\n${period(entry)}`;
  button.addEventListener("click", onClick);
  return button;
}
function showDetail(entry) {
  const content = $("detail-content");
  content.replaceChildren();
  content.append(element("span", `badge ${entry.source.game}`, games[entry.source.game].name));
  const heading = element("h2", "", entry.title);
  heading.id = "detail-title";
  content.append(heading, typeTags([entry.type]), element("p", "detail-meta", period(entry)));
  if (entry.family) {
    const parent = element("button", "family-link", `${isSong(entry) ? "関連イベント" : "親イベント"}：${entry.family.title}`);
    parent.type = "button";
    parent.addEventListener("click", () => showFamily(entry.family));
    content.append(parent);
  }
  if (entry.start !== entry.official_start || entry.end !== entry.official_end) {
    const day = entry.start_is_deadline ? entry.start : entry.end;
    if (day) content.append(element("p", "detail-meta", `最終利用日：${day.replaceAll("-", "/")}（上記日時で終了）`));
  }
  if (entry.songs.length) {
    content.append(element("h3", "", "対象楽曲"));
    const list = element("ul");
    entry.songs.forEach((song) => list.append(element("li", "", song)));
    content.append(list);
  }
  content.append(element("h3", "", "出典"));
  for (const origin of entry.origins || [{ source: entry.source }]) {
    const source = element("p");
    try {
      const url = new URL(origin.source.url);
      if (["https:", "http:"].includes(url.protocol)) {
        const link = element("a", "source-link", origin.source.title);
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        source.append(link);
      }
    } catch { }
    if (!source.children.length) source.textContent = origin.source.title;
    content.append(source, element("p", "detail-meta", `記事公開日：${origin.source.date || "不明"}`));
  }
  if (!$("detail").open) $("detail").showModal();
}
function showFamily(family) {
  const content = $("detail-content");
  content.replaceChildren();
  content.append(element("span", `badge ${family.source.game}`, games[family.source.game].name));
  const heading = element("h2", "", family.title);
  heading.id = "detail-title";
  content.append(heading, typeTags(itemTypes(family)), element("p", "detail-meta", period(family)));
  const contents = family.members.filter((member) => !isSong(member));
  const songs = family.members.filter(isSong);
  content.append(element("h3", "", `含まれる告知（${contents.length}件）`));
  const list = element("div", "family-members");
  contents.forEach((member) => list.append(listItem(member, period(member), () => showDetail(member))));
  content.append(list);
  if (songs.length) {
    content.append(element("h3", "", `関連楽曲（${songs.length}件）`));
    const songList = element("div", "family-members");
    songs.forEach((member) => songList.append(listItem(member, `${period(member)}・${member.songs.join("、")}`, () => showDetail(member))));
    content.append(songList);
  }
  if (!$("detail").open) $("detail").showModal();
}
function renderNow(all) {
  const order = Object.keys(games);
  const byGame = (a, b) => order.indexOf(a.source.game) - order.indexOf(b.source.game);
  const current = currentEntries(withFamilies(currentEntries(all))).sort((a, b) => endDate(a).localeCompare(endDate(b)) || byGame(a, b));
  const upcoming = upcomingEntries(all).sort((a, b) => a.start.localeCompare(b.start) || byGame(a, b));
  const shown = nowView === "current" ? current : upcoming;
  for (const [id, view, count] of [["tab-current", "current", current.length], ["tab-upcoming", "upcoming", upcoming.length]]) {
    const tab = $(id);
    tab.setAttribute("aria-selected", String(nowView === view));
    tab.tabIndex = nowView === view ? 0 : -1;
    tab.querySelector(".tab-count").textContent = count;
  }
  const list = $("now-list");
  list.setAttribute("aria-labelledby", nowView === "current" ? "tab-current" : "tab-upcoming");
  list.replaceChildren();
  if (!shown.length) list.append(element("p", "day-empty", nowView === "current" ? "現在開催中の項目はありません。" : "今後開催予定の項目はありません。"));
  shown.forEach((entry, index) => {
    const upcomingView = nowView === "upcoming";
    const left = upcomingView ? daysBetween(today, entry.start) : daysBetween(today, endDate(entry));
    const card = element("button", `now-card ${entry.source.game}${!upcomingView && left <= 3 ? " soon" : ""}`);
    card.type = "button";
    card.hidden = !nowExpanded && index >= nowLimit;
    card.title = `${games[entry.source.game].name}｜${entry.title}`;
    card.addEventListener("click", () => openItem(entry));
    const body = element("span", "now-body");
    body.append(element("span", "now-title", entry.title));
    const tags = typeTags(itemTypes(entry));
    body.append(tags);
    // 残り日数は本文から切り離した右列にまとめ、経過ゲージはカード幅いっぱいの最下段に置く。
    const status = element("span", "now-status");
    status.append(element("span", "now-left", upcomingView ? (left === 1 ? "明日から" : `${left}日後`) : left === 0 ? "今日まで" : `残り${left}日`));
    status.append(element("span", "now-period", isRange(entry) ? `${shortDate(entry.start)} – ${shortDate(endDate(entry))}` : shortDate(entry.start)));
    card.append(element("span", "item-game", games[entry.source.game].short), body, status);
    if (!upcomingView) {
      const total = daysBetween(entry.start, endDate(entry)) + 1;
      const progress = element("span", "now-progress");
      const bar = element("span");
      bar.style.width = `${Math.round((daysBetween(entry.start, today) + 1) / total * 100)}%`;
      progress.append(bar);
      progress.setAttribute("aria-hidden", "true");
      card.append(progress);
    }
    list.append(card);
  });
  const more = $("now-more");
  more.hidden = shown.length <= nowLimit;
  more.textContent = nowExpanded ? "折りたたむ" : `残り${shown.length - nowLimit}件を表示`;
  more.setAttribute("aria-expanded", String(nowExpanded));
}
function renderDay() {
  const panel = $("day-panel");
  panel.replaceChildren();
  const date = parseDate(selected);
  panel.append(element("h3", "day-title", `${date.getUTCMonth() + 1}月${date.getUTCDate()}日（${weekdayNames[date.getUTCDay()]}）`));
  const groups = [
    ["この日から", dated.filter((entry) => entry.start === selected),
      (entry) => isRange(entry) ? `${shortDate(endDate(entry))}まで` : entry.open_ended ? "終了日未定" : entry.start_time],
    ["この日まで", dated.filter((entry) => isRange(entry) && endDate(entry) === selected),
      (entry) => `${shortDate(entry.start)}から・最終日${entry.end_time ? ` ${entry.end_time}` : ""}`],
    ["開催中", dated.filter((entry) => isRange(entry) && entry.start < selected && endDate(entry) > selected),
      (entry) => `残り${daysBetween(selected, endDate(entry))}日`],
  ];
  for (const [label, list, note] of groups) {
    if (!list.length) continue;
    const group = element("details", "day-group");
    // 開催中は件数が多くなりやすいため、多い場合は畳んで開始・終了を先に見せる。
    group.open = label !== "開催中" || list.length <= 8 || !panel.querySelector(".day-group");
    const summary = element("summary", "", label);
    summary.append(element("span", "group-count", `${list.length}件`));
    group.append(summary, ...list.sort(byGameAndTitle).map((entry) => listItem(entry, note(entry))));
    panel.append(group);
  }
  if (!panel.querySelector(".day-group")) panel.append(element("p", "day-empty", "この日に該当する項目はありません。"));
}
function selectDay(key) {
  selected = key;
  document.querySelectorAll(".day").forEach((cell) => {
    const active = cell.dataset.date === key;
    cell.classList.toggle("selected", active);
    cell.setAttribute("aria-pressed", String(active));
  });
  renderDay();
  if (matchMedia("(max-width: 960px)").matches) $("day-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderMonth(first, last) {
  const calendar = $("calendar");
  calendar.replaceChildren();
  const weekdays = element("div", "weekdays");
  weekdayNames.forEach((day) => weekdays.append(element("span", "", day)));
  calendar.append(weekdays);
  const gridFirst = offsetDate(first, -parseDate(first).getUTCDay());
  const gridLast = offsetDate(last, 6 - parseDate(last).getUTCDay());
  for (let weekStart = gridFirst; weekStart <= gridLast; weekStart = offsetDate(weekStart, 7)) {
    const week = element("div", "week");
    for (let day = 0; day < 7; day++) renderDayCell(week, offsetDate(weekStart, day), day);
    calendar.append(week);
  }
}
function renderDayCell(week, key, column) {
  const weekday = parseDate(key).getUTCDay();
  const outside = !key.startsWith(month);
  const cell = element("button", `day${outside ? " outside" : ""}${key === today ? " today" : ""}${key === selected ? " selected" : ""}${weekdayClass(key, weekday)}`);
  cell.type = "button";
  cell.dataset.date = key;
  cell.style.gridColumn = String(column + 1);
  const time = element("time", "", String(Number(key.slice(8))));
  time.dateTime = key;
  if (key === today) time.setAttribute("aria-current", "date");
  cell.append(time);
  const begins = dated.filter((entry) => entry.start === key);
  const ends = dated.filter((entry) => isRange(entry) && endDate(entry) === key);
  // 1日に数十件始まることがあるため、セルにはゲームごとの件数だけを置き、内容は日別パネルで見せる。
  for (const game of Object.keys(games)) {
    const list = begins.filter((entry) => entry.source.game === game);
    if (!list.length) continue;
    const chip = element("span", `day-chip ${game}`);
    chip.dataset.count = list.length;
    chip.append(element("b", "", games[game].short), element("span", "chip-text", list.length === 1 ? list[0].title : `${list.length}件`));
    cell.append(chip);
  }
  if (ends.length) cell.append(element("span", "day-end", `${ends.length}件 終了`));
  cell.setAttribute("aria-label", `${Number(key.slice(5, 7))}月${Number(key.slice(8))}日・開始${begins.length}件${ends.length ? `・終了${ends.length}件` : ""}`);
  cell.setAttribute("aria-pressed", String(key === selected));
  cell.addEventListener("click", () => {
    if (!outside) return selectDay(key);
    month = key.slice(0, 7);
    selected = key;
    render();
  });
  week.append(cell);
}
function renderTimeline(ranges, first, last) {
  const timeline = $("timeline");
  timeline.replaceChildren();
  $("timeline-empty").hidden = ranges.length !== 0;
  timeline.hidden = ranges.length === 0;
  if (!ranges.length) return;
  const days = daysBetween(first, last) + 1;
  timeline.style.setProperty("--days", days);
  const corner = element("div", "tl-corner", "項目");
  timeline.append(corner);
  const shades = [];
  for (let day = 0; day < days; day++) {
    const key = offsetDate(first, day);
    const weekday = parseDate(key).getUTCDay();
    const head = element("div", `tl-day${weekdayClass(key, weekday)}${key === today ? " today" : ""}`);
    head.style.gridColumn = String(day + 2);
    head.append(element("b", "", String(day + 1)), element("span", "", weekdayNames[weekday]));
    timeline.append(head);
    // 日ごとの縦罫線。土日祝はこの列に網掛けも重ねる。
    const shade = element("div", `tl-col${weekday === 0 || weekday === 6 || holidays.has(key) ? " tl-weekend" : ""}`);
    shade.style.gridColumn = String(day + 2);
    shades.push(shade);
  }
  let row = 2;
  for (const game of Object.keys(games)) {
    const list = ranges.filter((entry) => entry.source.game === game)
      .sort((a, b) => a.start.localeCompare(b.start) || endDate(a).localeCompare(endDate(b)) || a.title.localeCompare(b.title, "ja"));
    if (!list.length) continue;
    const header = element("button", `tl-group ${game}`);
    header.type = "button";
    header.style.gridRow = String(row++);
    header.setAttribute("aria-expanded", "true");
    header.append(element("span", "tl-caret", "▾"), element("span", "tl-group-name", games[game].name), element("span", "group-count", `${list.length}件`));
    const groupLine = element("div", "tl-line tl-group-line");
    groupLine.style.gridRow = header.style.gridRow;
    timeline.append(groupLine, header);
    const groupNodes = [];
    const addRow = (entry, child) => {
      const family = entry.members ? { expanded: false, nodes: [] } : null;
      const label = family ? listItem(entry, undefined, () => {
        family.expanded = !family.expanded;
        label.setAttribute("aria-expanded", String(family.expanded));
        family.nodes.forEach((node) => { node.familyHidden = !family.expanded; node.hidden = node.familyHidden; });
      }) : listItem(entry);
      // 行を1段に収めるため、種類はタグではなく行の背景色で示す。
      const typeName = family ? "親イベント" : types[entry.type] || entry.type;
      label.classList.add("tl-label");
      if (family) {
        label.classList.add("tl-family");
        label.setAttribute("aria-expanded", "false");
        label.prepend(element("span", "tl-caret", "▾"));
      } else label.dataset.type = entry.type;
      if (child) label.classList.add("tl-child");
      label.title += `
${typeName}`;
      label.querySelector(".type-tags").replaceWith(element("span", "sr-only", typeName));
      label.style.gridRow = String(row);
      const line = element("div", "tl-line");
      if (!family) line.dataset.type = entry.type;
      line.style.gridRow = String(row);
      const from = Math.max(0, daysBetween(first, entry.start));
      const to = Math.min(days - 1, daysBetween(first, endDate(entry)));
      // バーは行ラベルと同じ操作の補助なので、キーボード操作と読み上げはラベル側に任せる。
      const bar = element("button", `tl-bar ${game}${family ? " family" : ""}${entry.start < first ? " continues-before" : ""}${endDate(entry) > last ? " continues-after" : ""}`);
      bar.type = "button";
      bar.tabIndex = -1;
      bar.setAttribute("aria-hidden", "true");
      bar.style.gridRow = String(row++);
      bar.style.gridColumn = `${from + 2} / ${to + 3}`;
      bar.append(element("span", "", `${shortDate(entry.start)} – ${shortDate(endDate(entry))}`));
      bar.addEventListener("click", () => openItem(entry));
      groupNodes.push(line, label, bar);
      return family;
    };
    const shown = new Set();
    for (const entry of list) {
      if (!entry.family) {
        addRow(entry, false);
        continue;
      }
      if (shown.has(entry.family)) continue;
      shown.add(entry.family);
      const family = addRow(entry.family, false);
      // 子の告知は親の行の下に畳んでおき、親の行を押したときだけ見せる。
      for (const member of list.filter((item) => item.family === entry.family)) {
        const start = groupNodes.length;
        addRow(member, true);
        family.nodes.push(...groupNodes.slice(start));
      }
      family.nodes.forEach((node) => { node.familyHidden = true; node.hidden = true; });
    }
    timeline.append(...groupNodes);
    header.addEventListener("click", () => {
      const expanded = header.getAttribute("aria-expanded") !== "true";
      header.setAttribute("aria-expanded", String(expanded));
      groupNodes.forEach((node) => { node.hidden = !expanded || node.familyHidden === true; });
    });
  }
  // 罫線と網掛けは行の背景色より手前、バーより奥に描く。
  shades.forEach((shade) => { shade.style.gridRow = `2 / ${row}`; });
  timeline.append(...shades);
  if (today >= first && today <= last) {
    const marker = element("div", "tl-today");
    marker.style.gridColumn = String(daysBetween(first, today) + 2);
    marker.style.gridRow = `1 / ${row}`;
    timeline.append(marker);
  }
}
function render() {
  const [year, monthNumber] = month.split("-").map(Number);
  $("month-title").textContent = `${year}年 ${monthNumber}月`;
  $("month").value = month;
  const first = `${month}-01`;
  const last = dateKey(new Date(Date.UTC(year, monthNumber, 0)));
  const all = filteredEntries();
  entries.forEach((entry) => { delete entry.family; });
  groupFamilies(all);
  dated = all.filter((entry) => entry.start);
  const starts = dated.filter((entry) => entry.start >= first && entry.start <= last);
  const ranges = dated.filter((entry) => isRange(entry) && entry.start <= last && endDate(entry) >= first);
  $("empty").hidden = starts.length + ranges.length !== 0;
  if (!selected.startsWith(month)) selected = today.startsWith(month) ? today : starts.map((entry) => entry.start).sort()[0] || first;
  renderNow(all);
  renderMonth(first, last);
  renderDay();
  renderTimeline(ranges, first, last);
  pinTimelineHead();
  const undated = all.filter((entry) => !entry.start);
  $("undated-count").textContent = `${undated.length}件`;
  $("undated-list").replaceChildren(...undated.map((entry) => listItem(entry)));
  $("undated").hidden = undated.length === 0;
}
// 祝日データは補助情報なので、取得できなくても土日だけでカレンダーを表示する。
async function loadHolidays() {
  try {
    const response = await fetch("https://holidays-jp.github.io/api/v1/date.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    holidays = new Set(Object.keys(await response.json()).filter(validDate));
    if (entries.length) render();
  } catch (error) {
    console.warn("Holidays could not be loaded", error);
  }
}
function calendarEntry(entry, source) {
  return {
    ...entry, official_start: entry.start, official_end: entry.end,
    start: validDate(entry.calendar_start) ? entry.calendar_start : validDate(entry.start) ? entry.start : null,
    end: validDate(entry.calendar_end) ? entry.calendar_end : entry.end,
    source,
  };
}
function mergeDuplicates(list) {
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
    [...new Set(entry.songs || [])].sort()]);
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
function mergeSongOverlaps(list) {
  const key = (entry) => JSON.stringify([entry.source.game, entry.service ?? null, entry.type, entry.start]);
  const linked = list.filter((entry) => isSong(entry) && entry.start && subjectKey(entry.subject));
  return list.flatMap((entry) => {
    if (!isSong(entry) || !entry.start || subjectKey(entry.subject)) return [entry];
    const targets = linked.filter((item) => key(item) === key(entry) && item.songs.some((song) => entry.songs.includes(song)));
    if (!targets.length) return [entry];
    targets.forEach((target) => target.origins.push(...entry.origins));
    const songs = entry.songs.filter((song) => !targets.some((target) => target.songs.includes(song)));
    return songs.length ? [{ ...entry, songs }] : [];
  });
}
async function load() {
  $("loading").hidden = false;
  $("error").hidden = true;
  try {
    const response = await fetch("./entries.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (![2, 3, 4, 5, 6].includes(data.schema_version) || data.mode !== "extraction" || !Array.isArray(data.articles)) throw new Error("Unsupported data");
    const extracted = data.articles.filter((article) => article.status !== "failed" && games[article.source.game])
      .flatMap((article) => article.entries.map((entry) => calendarEntry(entry, article.source)));
    entries = mergeSongOverlaps(mergeDuplicates(extracted));
    $("type").replaceChildren(new Option("すべての種類", ""));
    [...new Set(entries.map((entry) => entry.type))].sort().forEach((type) => $("type").add(new Option(types[type] || type, type)));
    render();
  } catch (error) {
    $("error").hidden = false;
    $("calendar").replaceChildren();
    $("day-panel").replaceChildren();
    $("timeline").replaceChildren();
    $("now-list").replaceChildren();
    $("now-more").hidden = true;
    $("undated").hidden = true;
    $("empty").hidden = true;
    console.error("Calendar data could not be loaded", error);
  } finally { $("loading").hidden = true; }
}
for (const [game, { name }] of Object.entries(games)) {
  const label = element("label", `game-filter ${game}`);
  const input = element("input");
  input.type = "checkbox";
  input.value = game;
  input.checked = true;
  input.addEventListener("change", () => {
    if (input.checked) selectedGames.add(game); else selectedGames.delete(game);
    render();
  });
  label.append(input, document.createTextNode(name));
  $("games").append(label);
}
function changeMonth(delta) {
  const date = parseDate(`${month}-01`);
  date.setUTCMonth(date.getUTCMonth() + delta);
  month = dateKey(date).slice(0, 7);
  render();
}
$("prev").addEventListener("click", () => changeMonth(-1));
$("next").addEventListener("click", () => changeMonth(1));
$("today").addEventListener("click", () => { month = today.slice(0, 7); selected = today; render(); });
$("month").addEventListener("change", (event) => {
  if (/^\d{4}-\d{2}$/.test(event.target.value) && Number(event.target.value.slice(0, 4)) >= 100) {
    month = event.target.value;
    render();
  }
});
$("type").addEventListener("change", render);
$("search").addEventListener("input", render);
$("retry").addEventListener("click", load);
$("now-more").addEventListener("click", () => { nowExpanded = !nowExpanded; renderNow(filteredEntries()); });
function selectNowView(view) {
  nowView = view;
  nowExpanded = false;
  render();
}
for (const tab of document.querySelectorAll(".now-tab")) {
  tab.addEventListener("click", () => selectNowView(tab.dataset.view));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    selectNowView(nowView === "current" ? "upcoming" : "current");
    $(nowView === "current" ? "tab-current" : "tab-upcoming").focus();
  });
}
// 開催期間タイムラインは縦スクロールをページに任せているため、見出し行の追従はここで行う。
function pinTimelineHead() {
  const timeline = $("timeline");
  if (timeline.hidden) return;
  const head = timeline.querySelector(".tl-corner");
  if (!head) return;
  const top = timeline.getBoundingClientRect().top;
  const shift = Math.max(0, Math.min(-top, timeline.offsetHeight - head.offsetHeight));
  timeline.style.setProperty("--head-shift", `${shift}px`);
}
addEventListener("scroll", pinTimelineHead, { passive: true });
addEventListener("resize", pinTimelineHead);
loadHolidays();
load();
