<script>
  import { offsetDate, parseDate, today, weekdayNames } from "../lib/dates.js";
  import { endDate, games, isRange } from "../lib/entries.js";
  import { weekdayClass } from "./weekday.js";

  let { month, range, selected, dated, holidays, onselect } = $props();
  const weeks = $derived.by(() => {
    const gridFirst = offsetDate(range.first, -parseDate(range.first).getUTCDay());
    const gridLast = offsetDate(range.last, 6 - parseDate(range.last).getUTCDay());
    const result = [];
    for (let weekStart = gridFirst; weekStart <= gridLast; weekStart = offsetDate(weekStart, 7)) {
      result.push(Array.from({ length: 7 }, (_, day) => offsetDate(weekStart, day)));
    }
    return result;
  });
</script>

<div class="weekdays">
  {#each weekdayNames as day (day)}<span>{day}</span>{/each}
</div>
{#each weeks as week (week[0])}
  <div class="week">
    {#each week as key, column (key)}
      {@const outside = !key.startsWith(month)}
      {@const begins = dated.filter((entry) => entry.start === key)}
      {@const ends = dated.filter((entry) => isRange(entry) && endDate(entry) === key)}
      <button
        class="day{outside ? ' outside' : ''}{key === today ? ' today' : ''}{key === selected ? ' selected' : ''}{weekdayClass(key, parseDate(key).getUTCDay(), holidays)}"
        type="button"
        data-date={key}
        style:grid-column={String(column + 1)}
        aria-label="{Number(key.slice(5, 7))}月{Number(key.slice(8))}日・開始{begins.length}件{ends.length ? `・終了${ends.length}件` : ''}"
        aria-pressed={key === selected}
        onclick={() => onselect(key, outside)}
      >
        <time datetime={key} aria-current={key === today ? "date" : undefined}>{Number(key.slice(8))}</time>
        <!-- 1日に数十件始まることがあるため、セルにはゲームごとの件数だけを置き、内容は日別パネルで見せる。 -->
        {#each Object.keys(games) as game (game)}
          {@const list = begins.filter((entry) => entry.source.game === game)}
          {#if list.length}
            <span class="day-chip {game}" data-count={list.length}>
              <b>{games[game].short}</b><span class="chip-text">{list.length === 1 ? list[0].title : `${list.length}件`}</span>
            </span>
          {/if}
        {/each}
        {#if ends.length}<span class="day-end">{ends.length}件 終了</span>{/if}
      </button>
    {/each}
  </div>
{/each}
