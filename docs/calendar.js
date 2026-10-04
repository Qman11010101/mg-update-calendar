"use strict";

const games = {
  chunithm: { name: "CHUNITHM", short: "CHU" },
  maimai: { name: "maimai", short: "mai" },
  ongeki: { name: "オンゲキ", short: "ONG" },
  chunithm_intl: { name: "CHUNITHM International", short: "INT" },
};
const types = {
  song_add: "楽曲追加", song_unlock: "楽曲の一般開放・解禁緩和", version_launch: "バージョン稼働",
  maintenance: "メンテナンス", service_change: "サービス変更", other: "その他", event: "イベント",
  map_add: "マップ追加・拡張", quest: "チュウニズムクエスト", mission: "ミッション",
  course_add: "認定コース追加", ultima_add: "ULTIMA譜面追加", worlds_end_add: "WORLD’S END譜面追加",
  area_add: "ちほー追加・拡張", friend_battle: "オトモダチ対戦", remaster_add: "Re:MASTER譜面追加",
  dx_chart_add: "でらっくす譜面追加", standard_chart_add: "スタンダード譜面追加", utage_add: "宴譜面追加",
  chapter_add: "チャプター追加", ranking: "ランキング", technical_challenge: "テクニカルチャレンジ",
  gacha: "ガチャ", login_bonus: "ログインボーナス", lunatic_add: "LUNATIC譜面追加",
};
const weekdayNames = ["日", "月", "火", "水", "木", "金", "土"];
const $ = (id) => document.getElementById(id);
const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date());
let month = today.slice(0, 7);
let selected = today;
let entries = [];
let dated = [];
let nowExpanded = false;
const nowLimit = 8;
const selectedGames = new Set(Object.keys(games));

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function dateKey(date) { return date.toISOString().slice(0, 10); }
function parseDate(value) { return new Date(`${value}T00:00:00Z`); }
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
  const start = entry.start.replaceAll("-", "/") + (entry.start_time ? ` ${entry.start_time}` : "");
  if (entry.open_ended) return `${start}〜（終了日未定）`;
  return entry.end ? `${start} 〜 ${entry.end.replaceAll("-", "/")}${entry.end_time ? ` ${entry.end_time}` : ""}` : start;
}
function filteredEntries() {
  const query = $("search").value.normalize("NFKC").toLocaleLowerCase().trim();
  return entries.filter((entry) => selectedGames.has(entry.source.game) &&
    (!$("type").value || entry.type === $("type").value) &&
    (!query || [entry.title, ...entry.songs, entry.source.title].join(" ").normalize("NFKC").toLocaleLowerCase().includes(query)));
}
function byGameAndTitle(a, b) {
  const order = Object.keys(games);
  return order.indexOf(a.source.game) - order.indexOf(b.source.game) || a.title.localeCompare(b.title, "ja");
}
// コラボのイベント・クエスト・ミッションなど、同じゲーム・同じ期間の項目を1本のリボン・1枚のカードにまとめる。
function periodGroups(list) {
  const groups = new Map();
  for (const entry of list) {
    const key = `${entry.source.game}|${entry.start}|${endDate(entry)}`;
    if (!groups.has(key)) groups.set(key, { game: entry.source.game, start: entry.start, end: endDate(entry), entries: [] });
    groups.get(key).entries.push(entry);
  }
  const rank = (entry) => entry.type === "event" ? 0 : ["version_launch", "map_add", "area_add", "chapter_add"].includes(entry.type) ? 1 : 2;
  return [...groups.values()].map((group) => {
    group.entries.sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title, "ja"));
    return group;
  });
}
function groupLabel(group) {
  return `${group.entries[0].title}${group.entries.length > 1 ? ` ほか${group.entries.length - 1}件` : ""}`;
}
function listItem(entry, note) {
  const button = element("button", `item ${entry.source.game}`);
  button.type = "button";
  button.append(element("span", "item-game", games[entry.source.game].short));
  const body = element("span", "item-body");
  body.append(element("span", "item-title", entry.title));
  body.append(element("span", "item-meta", [types[entry.type] || entry.type, note].filter(Boolean).join(" ・ ")));
  button.append(body);
  if (entry.status === "needs_review") button.append(element("span", "review-dot", "要確認"));
  button.title = `${games[entry.source.game].name}｜${entry.title}\n${period(entry)}`;
  button.addEventListener("click", () => showDetail(entry));
  return button;
}
function showDetail(entry) {
  const content = $("detail-content");
  content.replaceChildren();
  content.append(element("span", `badge ${entry.source.game}`, games[entry.source.game].name));
  const heading = element("h2", "", entry.title);
  heading.id = "detail-title";
  content.append(heading, element("p", "detail-meta", `${types[entry.type] || entry.type} ・ ${period(entry)}`));
  if (entry.source.game === "chunithm_intl") content.append(element("p", "detail-meta", "海外版の日時は告知の表記です。タイムゾーンは未確認です。"));
  if (entry.songs.length) {
    content.append(element("h3", "", "対象楽曲"));
    const list = element("ul");
    entry.songs.forEach((song) => list.append(element("li", "", song)));
    content.append(list);
  }
  if (entry.status === "needs_review") {
    const review = element("section", "review");
    review.append(element("h3", "", "要確認の情報"));
    const list = element("ul");
    entry.review_reasons.forEach((reason) => list.append(element("li", "", reason)));
    review.append(list);
    content.append(review);
  }
  if (entry.date_text) content.append(element("h3", "", "告知の日付表記"), element("p", "evidence", entry.date_text));
  content.append(element("h3", "", "原文の根拠"), element("p", "evidence", entry.evidence));
  content.append(element("h3", "", "出典"), element("p", "", entry.source.title));
  content.append(element("p", "detail-meta", `記事公開日：${entry.source.date || "不明"}`));
  try {
    const url = new URL(entry.source.url);
    if (["https:", "http:"].includes(url.protocol)) {
      const link = element("a", "source-link", "公式のお知らせを開く ↗");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      content.append(link);
    }
  } catch { /* 不正なURLはリンク化せず、出典タイトルだけを表示する。 */ }
  $("detail").showModal();
}
function showGroup(group) {
  if (group.entries.length === 1) return showDetail(group.entries[0]);
  const content = $("detail-content");
  content.replaceChildren();
  content.append(element("span", `badge ${group.game}`, games[group.game].name));
  const heading = element("h2", "", groupLabel(group));
  heading.id = "detail-title";
  content.append(heading, element("p", "detail-meta", `${group.start.replaceAll("-", "/")} 〜 ${group.end.replaceAll("-", "/")}`));
  content.append(element("h3", "", "同じ期間の項目"));
  const list = element("div", "group-list");
  list.append(...group.entries.map((entry) => listItem(entry)));
  content.append(list);
  $("detail").showModal();
}
function renderNow(all) {
  const active = all.filter((entry) => entry.start && isRange(entry) && entry.start <= today && endDate(entry) >= today);
  const order = Object.keys(games);
  const groups = periodGroups(active).sort((a, b) => a.end.localeCompare(b.end) || order.indexOf(a.game) - order.indexOf(b.game));
  $("now-note").textContent = active.length ? `${shortDate(today)}時点・${active.length}件。終了が近い順` : "";
  const list = $("now-list");
  list.replaceChildren();
  if (!groups.length) list.append(element("p", "day-empty", "現在開催中の項目はありません。"));
  groups.forEach((group, index) => {
    const left = daysBetween(today, group.end);
    const total = daysBetween(group.start, group.end) + 1;
    const card = element("button", `now-card ${group.game}${left <= 3 ? " soon" : ""}`);
    card.type = "button";
    card.hidden = !nowExpanded && index >= nowLimit;
    card.title = `${games[group.game].name}｜${group.entries.map((entry) => entry.title).join("\n")}`;
    card.addEventListener("click", () => showGroup(group));
    const head = element("div", "now-head");
    head.append(element("span", "item-game", games[group.game].short), element("span", "now-period", `${shortDate(group.start)} 〜 ${shortDate(group.end)}`), element("span", "now-left", left === 0 ? "今日まで" : `残り${left}日`));
    const progress = element("div", "now-progress");
    const bar = element("span");
    bar.style.width = `${Math.round((daysBetween(group.start, today) + 1) / total * 100)}%`;
    progress.append(bar);
    progress.setAttribute("aria-hidden", "true");
    const [main, ...rest] = group.entries;
    card.append(head, progress, element("span", "now-title", main.title));
    card.append(element("span", "item-meta", rest.length ? `${types[main.type] || main.type}＋${[...new Set(rest.map((entry) => types[entry.type] || entry.type))].join("・")}（計${group.entries.length}件）` : types[main.type] || main.type));
    list.append(card);
  });
  const more = $("now-more");
  more.hidden = groups.length <= nowLimit;
  more.textContent = nowExpanded ? "折りたたむ" : `残り${groups.length - nowLimit}件を表示`;
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
  const cell = element("button", `day${outside ? " outside" : ""}${key === today ? " today" : ""}${key === selected ? " selected" : ""}${weekday === 0 ? " sunday" : weekday === 6 ? " saturday" : ""}`);
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
    const head = element("div", `tl-day${weekday === 0 ? " sunday" : weekday === 6 ? " saturday" : ""}${key === today ? " today" : ""}`);
    head.style.gridColumn = String(day + 2);
    head.append(element("b", "", String(day + 1)), element("span", "", weekdayNames[weekday]));
    timeline.append(head);
    if (weekday === 0 || weekday === 6) {
      const shade = element("div", "tl-weekend");
      shade.style.gridColumn = String(day + 2);
      shades.push(shade);
    }
  }
  timeline.append(...shades);
  let row = 2;
  for (const game of Object.keys(games)) {
    const list = ranges.filter((entry) => entry.source.game === game)
      .sort((a, b) => a.start.localeCompare(b.start) || endDate(a).localeCompare(endDate(b)) || a.title.localeCompare(b.title, "ja"));
    if (!list.length) continue;
    const header = element("button", `tl-group ${game}`);
    header.type = "button";
    header.style.gridRow = String(row++);
    header.setAttribute("aria-expanded", "true");
    header.append(element("span", "tl-caret", "▾"), document.createTextNode(games[game].name), element("span", "group-count", `${list.length}件`));
    timeline.append(header);
    const groupNodes = [];
    for (const entry of list) {
      const label = listItem(entry);
      label.classList.add("tl-label");
      label.style.gridRow = String(row);
      const line = element("div", "tl-line");
      line.style.gridRow = String(row);
      const from = Math.max(0, daysBetween(first, entry.start));
      const to = Math.min(days - 1, daysBetween(first, endDate(entry)));
      // バーは行ラベルと同じ操作の補助なので、キーボード操作と読み上げはラベル側に任せる。
      const bar = element("button", `tl-bar ${game}${entry.start < first ? " continues-before" : ""}${endDate(entry) > last ? " continues-after" : ""}`);
      bar.type = "button";
      bar.tabIndex = -1;
      bar.setAttribute("aria-hidden", "true");
      bar.style.gridRow = String(row++);
      bar.style.gridColumn = `${from + 2} / ${to + 3}`;
      bar.append(element("span", "", `${shortDate(entry.start)} – ${shortDate(endDate(entry))}`));
      bar.addEventListener("click", () => showDetail(entry));
      groupNodes.push(line, label, bar);
    }
    timeline.append(...groupNodes);
    header.addEventListener("click", () => {
      const expanded = header.getAttribute("aria-expanded") !== "true";
      header.setAttribute("aria-expanded", String(expanded));
      groupNodes.forEach((node) => { node.hidden = !expanded; });
    });
  }
  shades.forEach((shade) => { shade.style.gridRow = `2 / ${row}`; });
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
  dated = all.filter((entry) => entry.start);
  const starts = dated.filter((entry) => entry.start >= first && entry.start <= last);
  const ranges = dated.filter((entry) => isRange(entry) && entry.start <= last && endDate(entry) >= first);
  $("count").textContent = `この月に始まる項目 ${starts.length}件 ・ 期間のある項目 ${ranges.length}件`;
  $("empty").hidden = starts.length + ranges.length !== 0;
  if (!selected.startsWith(month)) selected = today.startsWith(month) ? today : starts.map((entry) => entry.start).sort()[0] || first;
  renderNow(all);
  renderMonth(first, last);
  renderDay();
  renderTimeline(ranges, first, last);
  const undated = all.filter((entry) => !entry.start);
  $("undated-count").textContent = `${undated.length}件`;
  $("undated-list").replaceChildren(...undated.map((entry) => listItem(entry)));
  $("undated").hidden = undated.length === 0;
}
async function load() {
  $("loading").hidden = false;
  $("error").hidden = true;
  try {
    const response = await fetch("./entries.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.schema_version !== 2 || data.mode !== "extraction" || !Array.isArray(data.articles)) throw new Error("Unsupported data");
    entries = data.articles.filter((article) => article.status !== "failed" && games[article.source.game]).flatMap((article) => article.entries.map((entry) => ({
      ...entry, start: validDate(entry.start) ? entry.start : null,
      source: article.source, status: article.status, review_reasons: article.review_reasons || [],
    })));
    $("type").replaceChildren(new Option("すべての種類", ""));
    [...new Set(entries.map((entry) => entry.type))].sort().forEach((type) => $("type").add(new Option(types[type] || type, type)));
    const cancellations = data.articles.reduce((sum, article) => sum + (article.cancellations?.length || 0), 0);
    const failed = data.articles.filter((article) => article.status === "failed").length;
    $("data-note").textContent = `${data.articles.length}記事・${entries.length}エントリ。取り消し情報${cancellations}件はカレンダーに表示していません。${failed ? `抽出失敗の記事：${failed}件。` : ""}記事をまたぐ重複や取り消しの照合は未適用です。終了日未定の項目は開始日にのみ表示します。`;
    render();
  } catch (error) {
    $("error").hidden = false;
    $("calendar").replaceChildren();
    $("day-panel").replaceChildren();
    $("timeline").replaceChildren();
    $("now-list").replaceChildren();
    $("now-more").hidden = true;
    $("count").textContent = "";
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
load();
