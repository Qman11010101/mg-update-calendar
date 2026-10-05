<script>
  import { games, itemTypes, period } from "../lib/entries.js";
  import { openItem } from "./detail.svelte.js";
  import TypeTags from "./TypeTags.svelte";

  let { entry, note, songs, onclick = () => openItem(entry) } = $props();
</script>

<button
  class="item {entry.source.game}"
  type="button"
  title={`${games[entry.source.game].name}｜${entry.title}\n${period(entry)}`}
  {onclick}
>
  <span class="item-game">{games[entry.source.game].short}</span>
  <span class="item-body">
    <span class="item-title">{entry.title}</span>
    <TypeTags types={itemTypes(entry)}>
      {#if note}<span class="item-meta">{note}</span>{/if}
    </TypeTags>
    {#if songs?.length}
      <ul class="item-songs">
        {#each songs as song, index (index)}
          <li><span class="song-title">{song.title}</span>{#if song.artist}<span class="song-artist">{song.artist}</span>{/if}</li>
        {/each}
      </ul>
    {/if}
  </span>
</button>
