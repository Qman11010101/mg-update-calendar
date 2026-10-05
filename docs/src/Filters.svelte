<script>
  import { games, typeLabel } from "../lib/entries.js";

  let { types, selectedGames, type = $bindable(), query = $bindable() } = $props();

  function toggleGame(game, checked) {
    if (checked) selectedGames.add(game); else selectedGames.delete(game);
  }
</script>

<div class="filters">
  <fieldset id="games">
    <legend>ゲーム</legend>
    {#each Object.entries(games) as [game, { name }] (game)}
      <label class="game-filter {game}">
        <input
          type="checkbox"
          value={game}
          checked={selectedGames.has(game)}
          onchange={(event) => toggleGame(game, event.currentTarget.checked)}
        />{name}
      </label>
    {/each}
  </fieldset>
  <div class="filter-inputs">
    <label>種類<select id="type" bind:value={type}>
        <option value="">すべての種類</option>
        {#each types as group (group.label)}
          <optgroup label={group.label}>
            {#each group.types as value (value)}
              <option {value}>{typeLabel(value)}</option>
            {/each}
          </optgroup>
        {/each}
      </select></label>
    <label>キーワード<input id="search" type="search" placeholder="イベント・曲名を検索" bind:value={query} /></label>
  </div>
</div>
