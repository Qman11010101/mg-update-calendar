<script>
  import CalendarIcon from "@lucide/svelte/icons/calendar";
  import ChevronLeft from "@lucide/svelte/icons/chevron-left";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { today } from "../lib/dates.js";

  let { month, onpick } = $props();
  let open = $state(false);
  let year = $state(0);
  let root;

  function toggle() {
    year = Number(month.slice(0, 4));
    open = !open;
  }
  function pick(monthNumber) {
    open = false;
    onpick(`${year}-${String(monthNumber).padStart(2, "0")}`);
  }
  // 外側を押すかEscで閉じる。
  function closeOutside(event) {
    if (open && !root.contains(event.target)) open = false;
  }
  function closeOnEscape(event) {
    if (open && event.key === "Escape") open = false;
  }
</script>

<svelte:window onpointerdown={closeOutside} onkeydown={closeOnEscape} />

<div class="month-picker" bind:this={root}>
  <button id="month-pick" aria-label="表示する月を選ぶ" aria-expanded={open} aria-controls="month-picker-panel" onclick={toggle}>
    <CalendarIcon size={18} aria-hidden="true" />
  </button>
  {#if open}
    <div id="month-picker-panel" class="month-picker-panel" role="dialog" aria-label="表示する月">
      <div class="picker-year">
        <button aria-label="前の年" onclick={() => year--}><ChevronLeft size={16} aria-hidden="true" /></button>
        <span>{year}年</span>
        <button aria-label="次の年" onclick={() => year++}><ChevronRight size={16} aria-hidden="true" /></button>
      </div>
      <div class="picker-months">
        {#each Array.from({ length: 12 }, (_, index) => index + 1) as monthNumber (monthNumber)}
          {@const value = `${year}-${String(monthNumber).padStart(2, "0")}`}
          <button
            class:current={value === month}
            class:this-month={value === today.slice(0, 7)}
            aria-current={value === month ? "date" : undefined}
            onclick={() => pick(monthNumber)}
          >{monthNumber}月</button>
        {/each}
      </div>
    </div>
  {/if}
</div>
