<script>
  import { typeLabel } from "../lib/entries.js";

  let { types, children } = $props();
</script>

<span class="type-tags">
  {#each [...new Set(types)] as type (type)}
    <span class="type-tag" data-type={type}>{typeLabel(type)}</span>
  {/each}
  {@render children?.()}
</span>
