<script>
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { SvelteSet } from "svelte/reactivity";
  import { entriesStale, formatDateTime, monthRange, shiftMonth, validDate } from "../lib/dates.js";
  import { buildEntries, endDate, filterEntries, games, groupFamilies, isRange, typeGroups } from "../lib/entries.js";
  import DayPanel from "./DayPanel.svelte";
  import DetailDialog from "./DetailDialog.svelte";
  import Filters from "./Filters.svelte";
  import ListItem from "./ListItem.svelte";
  import MonthCalendar from "./MonthCalendar.svelte";
  import MonthPicker from "./MonthPicker.svelte";
  import NowList from "./NowList.svelte";
  import Timeline from "./Timeline.svelte";
  import { today } from "./today.svelte.js";

  let month = $state(today.date.slice(0, 7));
  let selected = $state(today.date);
  // 項目は表示時に entry.family を書き換えるため、プロキシにしない。
  let entries = $state.raw([]);
  let holidays = $state.raw(new Set());
  let updatedAt = $state(null);
  let status = $state("loading");
  let type = $state("");
  let query = $state("");
  let fetchedAt = 0;
  let loadingEntries = false;
  let dayPanel;
  const selectedGames = new SvelteSet(Object.keys(games));

  const ready = $derived(status === "ready");
  const range = $derived(monthRange(month));
  // 移動できる月は、項目のある最初の月から最後の月まで。絞り込みでは変えず、今月は項目がなくても含める。
  const bounds = $derived.by(() => {
    const months = entries.filter((entry) => entry.start).flatMap((entry) => [entry.start, endDate(entry)])
      .map((date) => date.slice(0, 7)).concat(today.date.slice(0, 7)).sort();
    return { first: months[0], last: months.at(-1) };
  });
  const types = $derived(typeGroups(entries));
  // 絞り込みのたびに親イベントを作り直し、前回の entry.family を付け替える。
  const all = $derived.by(() => {
    const list = filterEntries(entries, { games: selectedGames, type, query });
    entries.forEach((entry) => { delete entry.family; });
    groupFamilies(list);
    return list;
  });
  const dated = $derived(all.filter((entry) => entry.start));
  const undated = $derived(all.filter((entry) => !entry.start));
  const starts = $derived(dated.filter((entry) => entry.start >= range.first && entry.start <= range.last));
  const ranges = $derived(dated.filter((entry) => isRange(entry) && entry.start <= range.last && endDate(entry) >= range.first));

  function showMonth(value, day) {
    if (value < bounds.first || value > bounds.last) return;
    month = value;
    if (day) selected = day;
    else if (!selected.startsWith(month)) selected = today.date.startsWith(month) ? today.date : starts.map((entry) => entry.start).sort()[0] || range.first;
  }
  function selectDay(key, outside) {
    if (outside) return showMonth(key.slice(0, 7), key);
    selected = key;
    if (matchMedia("(max-width: 960px)").matches) dayPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  // 祝日データは補助情報なので、取得できなくても土日だけでカレンダーを表示する。
  async function loadHolidays() {
    try {
      const response = await fetch("https://holidays-jp.github.io/api/v1/date.json");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      holidays = new Set(Object.keys(await response.json()).filter(validDate));
    } catch (error) {
      console.warn("Holidays could not be loaded", error);
    }
  }
  async function load(options) {
    // 再読み込みボタンは click イベントを渡す。再取得だけ { refresh: true }。
    const refresh = options?.refresh === true;
    if (refresh && loadingEntries) return;
    loadingEntries = true;
    if (!refresh) status = "loading";
    try {
      // 開いたままの再取得はキャッシュを再検証しないと、定期更新が届かない。
      const response = await fetch("./entries.json", refresh ? { cache: "no-cache" } : undefined);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      entries = buildEntries(data);
      updatedAt = data.updated_at ?? null;
      fetchedAt = Date.now();
      if (!refresh) type = "";
      status = "ready";
    } catch (error) {
      if (!refresh) status = "error";
      console.error("Calendar data could not be loaded", error);
    } finally {
      loadingEntries = false;
    }
  }
  // タブを開き直したときと、表示中は1分ごとに、日本時間の日付と、古くなった掲載データを取り直す。
  // 表示したまま日付をまたいだときや、端末のスリープから戻ったときは visibilitychange が届かないため。
  function onVisible() {
    if (document.visibilityState !== "visible") return;
    today.refresh();
    if (entriesStale(fetchedAt)) load({ refresh: true });
  }
  $effect(() => {
    const timer = setInterval(onVisible, 60 * 1000);
    return () => clearInterval(timer);
  });
  loadHolidays();
  load();
</script>

<svelte:document onvisibilitychange={onVisible} />

<main>
  <section class="workspace" aria-label="アップデートカレンダー">
    <Filters {types} {selectedGames} bind:type bind:query />
    <NowList {all} {ready} />
    <div class="toolbar">
      <div class="month-navigation">
        <h2 id="month-title">{Number(month.slice(0, 4))}年 {Number(month.slice(5))}月</h2>
        <MonthPicker {month} {bounds} onpick={(value) => showMonth(value)} />
        <div class="month-stepper" role="group" aria-label="月の移動">
          <button id="prev" aria-label="前の月" disabled={month <= bounds.first} onclick={() => showMonth(shiftMonth(month, -1))}><ChevronLeft size={18} aria-hidden="true" /></button>
          <button id="today" onclick={() => showMonth(today.date.slice(0, 7), today.date)}>今月</button>
          <button id="next" aria-label="次の月" disabled={month >= bounds.last} onclick={() => showMonth(shiftMonth(month, 1))}><ChevronRight size={18} aria-hidden="true" /></button>
        </div>
      </div>
      {#if ready && formatDateTime(updatedAt)}
        <p class="updated-at">最終更新 <time datetime={updatedAt}>{formatDateTime(updatedAt)}</time></p>
      {/if}
    </div>
    <p id="loading" role="status" hidden={status !== "loading"}>カレンダーを読み込んでいます…</p>
    <div id="error" role="alert" hidden={status !== "error"}>
      <p>データを読み込めませんでした。</p>
      <button id="retry" onclick={load}>再読み込み</button>
    </div>
    <div class="month-layout">
      <div id="calendar" aria-labelledby="month-title">
        {#if ready}
          <MonthCalendar {month} {range} {selected} {dated} {holidays} onselect={selectDay} />
        {/if}
      </div>
      <aside id="day-panel" aria-live="polite" aria-label="選択した日のエントリ" bind:this={dayPanel}>
        {#if ready}
          <DayPanel {dated} {selected} />
        {/if}
      </aside>
    </div>
    <p id="empty" class="empty" hidden={!ready || starts.length + ranges.length !== 0}>この月に該当するエントリはありません。</p>
    <section class="timeline-section" aria-labelledby="timeline-title">
      <div class="section-head">
        <h3 id="timeline-title">開催期間</h3>
      </div>
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div class="timeline-scroll" tabindex="0" role="region" aria-label="開催期間タイムライン（横スクロール可能）">
        {#if ready}
          <Timeline {ranges} {range} {holidays} />
        {/if}
      </div>
      <p id="timeline-empty" class="empty" hidden={!ready || ranges.length !== 0}>この月に期間のある項目はありません。</p>
    </section>
  </section>
  <details id="undated" hidden={!ready || undated.length === 0}>
    <summary>日付不明のエントリ <span id="undated-count">{undated.length}件</span></summary>
    <div id="undated-list">
      {#each undated as entry (entry)}
        <ListItem {entry} />
      {/each}
    </div>
  </details>
</main>
<footer class="site-footer">
  <div class="footer-inner">
    <p class="copyright">© 2026 音ゲーツール置き場 / Qman's Tools Square</p>
    <p class="disclaimer">コンテンツはAIによって生成され、誤りを含む場合があります。</p>
    <p class="disclaimer">当サイトは非公式のファンサイトであり、株式会社セガをはじめとする関係者・関係会社とは一切関係ありません。</p>
  </div>
</footer>
<DetailDialog />
