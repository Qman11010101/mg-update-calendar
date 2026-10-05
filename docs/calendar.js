import {
  daysBetween, monthRange, offsetDate, parseDate, shiftMonth, shortDate, today, validDate, weekdayNames,
} from "./lib/dates.js";
import {
  buildEntries, dayGroups, endDate, entrySources, filterEntries, games, groupFamilies, isRange, isSong, itemTypes,
  lastUsableDay, nowLists, period, typeLabel,
} from "./lib/entries.js";

const $ = (id) => document.getElementById(id);
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
// 祝日は日曜と同じ見た目で扱う。
function weekdayClass(key, weekday) {
  return weekday === 0 || holidays.has(key) ? " sunday" : weekday === 6 ? " saturday" : "";
}
function filteredEntries() {
  return filterEntries(entries, { games: selectedGames, type: $("type").value, query: $("search").value });
}
function openItem(item) { return item.members ? showFamily(item) : showDetail(item); }
function typeTags(entryTypes) {
  const tags = element("span", "type-tags");
  for (const type of new Set(entryTypes)) {
    const tag = element("span", "type-tag", typeLabel(type));
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
  const lastDay = lastUsableDay(entry);
  if (lastDay) content.append(element("p", "detail-meta", `最終利用日：${lastDay.replaceAll("-", "/")}（上記日時で終了）`));
  if (entry.songs.length) {
    content.append(element("h3", "", "対象楽曲"));
    const list = element("ul");
    entry.songs.forEach((song) => list.append(element("li", "", song)));
    content.append(list);
  }
  content.append(element("h3", "", "関連記事"));
  for (const { title, url, date } of entrySources(entry)) {
    const source = element("p");
    if (url) {
      const link = element("a", "source-link", title);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      source.append(link);
    } else source.textContent = title;
    content.append(source, element("p", "detail-meta", `記事公開日：${date}`));
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
  const { current, upcoming } = nowLists(all);
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
  for (const { label, entries: list, note } of dayGroups(dated, selected)) {
    if (!list.length) continue;
    const group = element("details", "day-group");
    // 開催中は件数が多くなりやすいため、多い場合は畳んで開始・終了を先に見せる。
    group.open = label !== "開催中" || list.length <= 8 || !panel.querySelector(".day-group");
    const summary = element("summary", "", label);
    summary.append(element("span", "group-count", `${list.length}件`));
    group.append(summary, ...list.map((entry) => listItem(entry, note(entry))));
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
      const typeName = family ? "親イベント" : typeLabel(entry.type);
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
  $("month-title").textContent = `${Number(month.slice(0, 4))}年 ${Number(month.slice(5))}月`;
  $("month").value = month;
  const { first, last } = monthRange(month);
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
async function load() {
  $("loading").hidden = false;
  $("error").hidden = true;
  try {
    const response = await fetch("./entries.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    entries = buildEntries(await response.json());
    $("type").replaceChildren(new Option("すべての種類", ""));
    [...new Set(entries.map((entry) => entry.type))].sort().forEach((type) => $("type").add(new Option(typeLabel(type), type)));
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
  month = shiftMonth(month, delta);
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
