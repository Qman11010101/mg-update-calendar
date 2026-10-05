<script>
  import X from "@lucide/svelte/icons/x";
  import { entrySources, games, isSong, itemTypes, lastUsableDay, period } from "../lib/entries.js";
  import { detail, openItem } from "./detail.svelte.js";
  import ListItem from "./ListItem.svelte";
  import TypeTags from "./TypeTags.svelte";

  let dialog;
  const item = $derived(detail.item);

  $effect(() => {
    if (item && !dialog.open) dialog.showModal();
  });
  // closedby="any" は pointerup で閉じるため、スマホでは後続の click が下の要素に抜けて再オープンしてしまう。
  // click で閉じればタップがそこで消費される。
  function closeOnBackdrop(event) {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    const inside = event.clientX >= rect.left && event.clientX <= rect.right
      && event.clientY >= rect.top && event.clientY <= rect.bottom;
    if (!inside) dialog.close();
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<dialog
  id="detail"
  aria-labelledby="detail-title"
  bind:this={dialog}
  onclick={closeOnBackdrop}
  onclose={() => { detail.item = null; }}
>
  <form method="dialog">
    <!-- svelte-ignore a11y_autofocus -->
    <button class="close" aria-label="詳細を閉じる" autofocus><X size={20} aria-hidden="true" /></button>
  </form>
  <div id="detail-content">
    {#if item}
      <span class="badge {item.source.game}">{games[item.source.game].name}</span>
      <h2 id="detail-title">{item.title}</h2>
    {/if}
    {#if item?.members}
      {@const contents = item.members.filter((member) => !isSong(member))}
      {@const songs = item.members.filter(isSong)}
      <TypeTags types={itemTypes(item)} />
      <p class="detail-meta">{period(item)}</p>
      <h3>含まれる告知（{contents.length}件）</h3>
      <div class="family-members">
        {#each contents as member (member)}
          <ListItem entry={member} note={period(member)} />
        {/each}
      </div>
      {#if songs.length}
        <h3>関連楽曲（{songs.length}件）</h3>
        <div class="family-members">
          {#each songs as member (member)}
            <ListItem entry={member} note={period(member)} songs={member.songs} />
          {/each}
        </div>
      {/if}
    {:else if item}
      {@const lastDay = lastUsableDay(item)}
      <TypeTags types={[item.type]} />
      <p class="detail-meta">{period(item)}</p>
      {#if item.family}
        <button class="family-link" type="button" onclick={() => openItem(item.family)}>
          {isSong(item) ? "関連イベント" : "親イベント"}：{item.family.title}
        </button>
      {/if}
      {#if lastDay}
        <p class="detail-meta">最終利用日：{lastDay.replaceAll("-", "/")}（上記日時で終了）</p>
      {/if}
      {#if item.songs.length}
        <h3>対象楽曲</h3>
        <ul>
          {#each item.songs as song, index (index)}<li><strong>{song.title}</strong>{#if song.artist}{` / ${song.artist}`}{/if}</li>{/each}
        </ul>
      {/if}
      <h3>関連記事</h3>
      <div class="source-cards">
        {#each entrySources(item) as { title, url, date }, index (index)}
          <svelte:element
            this={url ? "a" : "div"}
            class="source-card"
            href={url || undefined}
            target={url ? "_blank" : undefined}
            rel={url ? "noopener noreferrer" : undefined}
          >
            <span class="source-title">{title}</span>
            <span class="detail-meta">{date}</span>
          </svelte:element>
        {/each}
      </div>
    {/if}
  </div>
</dialog>
