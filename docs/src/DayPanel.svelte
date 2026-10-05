<script>
  import { parseDate, weekdayNames } from "../lib/dates.js";
  import { dayGroups } from "../lib/entries.js";
  import ListItem from "./ListItem.svelte";

  let { dated, selected } = $props();
  const date = $derived(parseDate(selected));
  const groups = $derived(dayGroups(dated, selected).filter((group) => group.entries.length));
</script>

<h3 class="day-title">{date.getUTCMonth() + 1}月{date.getUTCDate()}日（{weekdayNames[date.getUTCDay()]}）</h3>
<!-- 開閉状態は表示内容が変わるたびに初期状態へ戻す。 -->
{#key groups}
  {#each groups as { label, entries, note }, index (label)}
    <!-- 開催中は件数が多くなりやすいため、多い場合は畳んで開始・終了を先に見せる。 -->
    <details class="day-group" open={label !== "開催中" || entries.length <= 8 || index === 0}>
      <summary>{label}<span class="group-count">{entries.length}件</span></summary>
      {#each entries as entry (entry)}
        <ListItem {entry} note={note(entry)} />
      {/each}
    </details>
  {/each}
{/key}
{#if !groups.length}
  <p class="day-empty">この日に該当する項目はありません。</p>
{/if}
