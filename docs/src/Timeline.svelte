<script>
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { SvelteSet } from "svelte/reactivity";
  import { daysBetween, offsetDate, parseDate, shortDate, today, weekdayNames } from "../lib/dates.js";
  import { endDate, games, period, typeLabel } from "../lib/entries.js";
  import { openItem } from "./detail.svelte.js";
  import { weekdayClass } from "./weekday.js";

  let { ranges, range, holidays } = $props();
  let timeline;
  const collapsedGames = new SvelteSet();
  let expandedFamilies = $state.raw(new Set());
  const days = $derived(daysBetween(range.first, range.last) + 1);
  const dayKeys = $derived(Array.from({ length: days }, (_, day) => offsetDate(range.first, day)));
  // グリッドの行番号を、ゲームの見出し行と各項目の行に順に割り当てる。
  const layout = $derived.by(() => {
    let row = 2;
    const groups = [];
    for (const game of Object.keys(games)) {
      const list = ranges.filter((entry) => entry.source.game === game)
        .sort((a, b) => a.start.localeCompare(b.start) || endDate(a).localeCompare(endDate(b)) || a.title.localeCompare(b.title, "ja"));
      if (!list.length) continue;
      const group = { game, count: list.length, row: row++, rows: [] };
      const addRow = (entry, parent) => group.rows.push({ entry, parent, row: row++ });
      const shown = new Set();
      for (const entry of list) {
        if (!entry.family) {
          addRow(entry, null);
          continue;
        }
        if (shown.has(entry.family)) continue;
        shown.add(entry.family);
        addRow(entry.family, null);
        // 子の告知は親の行の下に畳んでおき、親の行を押したときだけ見せる。
        for (const member of list.filter((item) => item.family === entry.family)) addRow(member, entry.family);
      }
      groups.push(group);
    }
    return { groups, lastRow: row };
  });

  function toggleGame(game) {
    if (collapsedGames.has(game)) collapsedGames.delete(game); else collapsedGames.add(game);
  }
  function toggleFamily(family) {
    const next = new Set(expandedFamilies);
    if (next.has(family)) next.delete(family); else next.add(family);
    expandedFamilies = next;
  }
  // 開催期間タイムラインは縦スクロールをページに任せているため、見出し行の追従はここで行う。
  function pinHead() {
    if (!timeline || timeline.hidden) return;
    const head = timeline.querySelector(".tl-corner");
    if (!head) return;
    const top = timeline.getBoundingClientRect().top;
    const shift = Math.max(0, Math.min(-top, timeline.offsetHeight - head.offsetHeight));
    timeline.style.setProperty("--head-shift", `${shift}px`);
  }
  $effect(() => {
    void layout;
    pinHead();
  });
</script>

<svelte:window onscroll={pinHead} onresize={pinHead} />

<div id="timeline" bind:this={timeline} hidden={!ranges.length} style:--days={days}>
  {#if ranges.length}
    <div class="tl-corner">項目</div>
    {#each dayKeys as key, day (key)}
      {@const weekday = parseDate(key).getUTCDay()}
      <div class="tl-day{weekdayClass(key, weekday, holidays)}{key === today ? ' today' : ''}" style:grid-column={String(day + 2)}>
        <b>{day + 1}</b><span>{weekdayNames[weekday]}</span>
      </div>
    {/each}
    {#each layout.groups as group (group.game)}
      {@const open = !collapsedGames.has(group.game)}
      <div class="tl-line tl-group-line" style:grid-row={String(group.row)}></div>
      <button
        class="tl-group {group.game}"
        type="button"
        style:grid-row={String(group.row)}
        aria-expanded={open}
        onclick={() => toggleGame(group.game)}
      >
        <ChevronDown class="tl-caret" size={14} aria-hidden="true" /><span class="tl-group-name">{games[group.game].name}</span><span class="group-count">{group.count}件</span>
      </button>
      {#each group.rows as { entry, parent, row } (row)}
        {@const family = Boolean(entry.members)}
        {@const hidden = !open || (parent !== null && !expandedFamilies.has(parent))}
        <!-- 行を1段に収めるため、種類はタグではなく行の背景色で示す。 -->
        {@const typeName = family ? "親イベント" : typeLabel(entry.type)}
        {@const from = Math.max(0, daysBetween(range.first, entry.start))}
        {@const to = Math.min(days - 1, daysBetween(range.first, endDate(entry)))}
        <div class="tl-line" data-type={family ? undefined : entry.type} style:grid-row={String(row)} {hidden}></div>
        <button
          class="item {entry.source.game} tl-label"
          class:tl-family={family}
          class:tl-child={parent !== null}
          data-type={family ? undefined : entry.type}
          type="button"
          title={`${games[entry.source.game].name}｜${entry.title}\n${period(entry)}\n${typeName}`}
          aria-expanded={family ? expandedFamilies.has(entry) : undefined}
          style:grid-row={String(row)}
          {hidden}
          onclick={() => (family ? toggleFamily(entry) : openItem(entry))}
        >
          {#if family}<ChevronDown class="tl-caret" size={14} aria-hidden="true" />{/if}
          <span class="item-game">{games[entry.source.game].short}</span>
          <span class="item-body">
            <span class="item-title">{entry.title}</span>
            <span class="sr-only">{typeName}</span>
          </span>
        </button>
        <!-- バーは行ラベルと同じ操作の補助なので、キーボード操作と読み上げはラベル側に任せる。 -->
        <button
          class="tl-bar {entry.source.game}"
          class:family
          class:continues-before={entry.start < range.first}
          class:continues-after={endDate(entry) > range.last}
          type="button"
          tabindex="-1"
          aria-hidden="true"
          style:grid-row={String(row)}
          style:grid-column="{from + 2} / {to + 3}"
          {hidden}
          onclick={() => openItem(entry)}
        ><span>{shortDate(entry.start)} – {shortDate(endDate(entry))}</span></button>
      {/each}
    {/each}
    <!-- 日ごとの縦罫線。土日祝はこの列に網掛けも重ねる。罫線と網掛けは行の背景色より手前、バーより奥に描く。 -->
    {#each dayKeys as key, day (key)}
      {@const weekday = parseDate(key).getUTCDay()}
      <div
        class="tl-col"
        class:tl-weekend={weekday === 0 || weekday === 6 || holidays.has(key)}
        style:grid-column={String(day + 2)}
        style:grid-row="2 / {layout.lastRow}"
      ></div>
    {/each}
    {#if today >= range.first && today <= range.last}
      <div class="tl-today" style:grid-column={String(daysBetween(range.first, today) + 2)} style:grid-row="1 / {layout.lastRow}"></div>
    {/if}
  {/if}
</div>
