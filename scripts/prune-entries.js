// 実行ディレクトリのentries.jsonから掲載を終えたエントリを除く。記事ごと除いたものはnews_all.jsonからも外し、
// 記事収集の差分更新で既知の記事として扱われ続けないようにする。残す期間の規則はdocs/lib/entries.jsのpruneDataを参照。
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { pruneData } from "../docs/lib/entries.js";

const read = (path) => JSON.parse(readFileSync(path, "utf8").replace(/^﻿/, ""));
// Python側の出力にそろえ、インデント2・非ASCII文字はそのまま・末尾改行で書き出す。
const write = (path, data) => writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`);

const { data, removed, entryCount } = pruneData(read("entries.json"));
if (entryCount || removed.length) write("entries.json", data);
let newsCount = 0;
if (removed.length && existsSync("news_all.json")) {
  const urls = new Set(removed);
  const news = read("news_all.json");
  const kept = news.filter((article) => !urls.has(article.url));
  newsCount = news.length - kept.length;
  if (newsCount) write("news_all.json", kept);
}
console.log(`pruned: entries=${entryCount}, articles=${removed.length}, news=${newsCount}`);
