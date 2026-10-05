import { readFileSync } from "node:fs";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
import { siteData } from "./docs/lib/entries.js";

// entries.jsonはPython側が書き出す抽出結果なのでバンドルせず、表示に必要な項目だけに詰めて置く。
// 開発サーバーでも同じ内容を返し、公開時との違いを出さない。
function entriesJson() {
  const compact = () => JSON.stringify(siteData(JSON.parse(readFileSync("docs/entries.json", "utf8").replace(/^﻿/, ""))));
  return {
    name: "entries-json",
    configureServer(server) {
      server.middlewares.use("/entries.json", (request, response) => {
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.end(compact());
      });
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "entries.json", source: compact() });
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
