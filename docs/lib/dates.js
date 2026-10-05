// 日付は "YYYY-MM-DD" の文字列で扱い、計算時だけUTCのDateに変換する。
export const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date());
export const weekdayNames = ["日", "月", "火", "水", "木", "金", "土"];

export function dateKey(date) { return date.toISOString().slice(0, 10); }
export function parseDate(value) { return new Date(`${value}T00:00:00Z`); }
export function offsetDate(value, days) {
  const date = parseDate(value);
  date.setUTCDate(date.getUTCDate() + days);
  return dateKey(date);
}
export function daysBetween(from, to) { return Math.round((parseDate(to) - parseDate(from)) / 86400000); }
export function shortDate(value) { return `${Number(value.slice(5, 7))}/${Number(value.slice(8))}`; }
export function validDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(parseDate(value).valueOf()) && dateKey(parseDate(value)) === value;
}
// "YYYY-MM" の月の初日と末日。
export function monthRange(month) {
  const [year, monthNumber] = month.split("-").map(Number);
  return { first: `${month}-01`, last: dateKey(new Date(Date.UTC(year, monthNumber, 0))) };
}
export function shiftMonth(month, delta) {
  const date = parseDate(`${month}-01`);
  date.setUTCMonth(date.getUTCMonth() + delta);
  return dateKey(date).slice(0, 7);
}
