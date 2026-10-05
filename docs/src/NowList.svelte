<script>
  import { daysBetween, shortDate, today } from "../lib/dates.js";
  import { endDate, games, isRange, itemTypes, nowLists } from "../lib/entries.js";
  import { openItem } from "./detail.svelte.js";
  import TypeTags from "./TypeTags.svelte";

  let { all, ready } = $props();
  const limit = 8;
  const views = [["current", "いま開催中"], ["upcoming", "今後開催"]];
  let view = $state("current");
  let expanded = $state(false);
  const lists = $derived(nowLists(all));
  const shown = $derived(lists[view]);

  function select(next) {
    view = next;
    expanded = false;
  }
  function onkeydown(event) {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    select(view === "current" ? "upcoming" : "current");
    document.getElementById(`tab-${view}`).focus();
  }
</script>

<section class="now" aria-label="開催状況">
  <div class="section-head now-tabs" role="tablist" aria-label="開催状況">
    {#each views as [key, label] (key)}
      <button
        id="tab-{key}"
        class="now-tab"
        type="button"
        role="tab"
        aria-selected={view === key}
        aria-controls="now-list"
        tabindex={view === key ? 0 : -1}
        onclick={() => select(key)}
        {onkeydown}
      >{label}<span class="tab-count">{ready ? lists[key].length : ""}</span></button>
    {/each}
  </div>
  <div id="now-list" role="tabpanel" aria-labelledby="tab-{view}">
    {#if ready}
      {#if !shown.length}
        <p class="day-empty">{view === "current" ? "現在開催中の項目はありません。" : "今後開催予定の項目はありません。"}</p>
      {/if}
      {#each shown as entry, index (entry)}
        {@const upcoming = view === "upcoming"}
        {@const left = upcoming ? daysBetween(today, entry.start) : daysBetween(today, endDate(entry))}
        <button
          class="now-card {entry.source.game}"
          class:soon={!upcoming && left <= 3}
          type="button"
          hidden={!expanded && index >= limit}
          title="{games[entry.source.game].name}｜{entry.title}"
          onclick={() => openItem(entry)}
        >
          <span class="item-game">{games[entry.source.game].short}</span>
          <span class="now-body">
            <span class="now-title">{entry.title}</span>
            <TypeTags types={itemTypes(entry)} />
          </span>
          <!-- 残り日数は本文から切り離した右列にまとめ、経過ゲージはカード幅いっぱいの最下段に置く。 -->
          <span class="now-status">
            <span class="now-left">{upcoming ? (left === 1 ? "明日から" : `${left}日後`) : left === 0 ? "今日まで" : `残り${left}日`}</span>
            <span class="now-period">{isRange(entry) ? `${shortDate(entry.start)} – ${shortDate(endDate(entry))}` : shortDate(entry.start)}</span>
          </span>
          {#if !upcoming}
            {@const total = daysBetween(entry.start, endDate(entry)) + 1}
            <span class="now-progress" aria-hidden="true">
              <span style:width="{Math.round((daysBetween(entry.start, today) + 1) / total * 100)}%"></span>
            </span>
          {/if}
        </button>
      {/each}
    {/if}
  </div>
  <button
    id="now-more"
    class="more-button"
    hidden={!ready || shown.length <= limit}
    aria-expanded={expanded}
    onclick={() => { expanded = !expanded; }}
  >{expanded ? "折りたたむ" : `残り${shown.length - limit}件を表示`}</button>
</section>
