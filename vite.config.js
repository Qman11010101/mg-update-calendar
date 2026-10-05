import { readFileSync } from "node:fs";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// entries.jsonはPython側が書き出すデータなのでバンドルせず、ビルド結果にそのまま置く。
function entriesJson() {
  return {
    name: "entries-json",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "entries.json", source: readFileSync("docs/entries.json") });
    },
  };
}

export default defineConfig({
  root: "docs",
  // GitHub Pagesはリポジトリ名のサブパスで公開されるため、相対パスで出力する。
  base: "./",
  publicDir: false,
  plugins: [svelte({ configFile: false }), entriesJson()],
  build: { outDir: "../_site", emptyOutDir: true },
});
