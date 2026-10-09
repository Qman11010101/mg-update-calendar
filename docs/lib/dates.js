// 日付は "YYYY-MM-DD" の文字列で扱い、計算時だけUTCのDateに変換する。
export const today = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date());
// ISO 8601の日時を日本時間の "YYYY/MM/DD HH:mm" にする。読めない値はnull。
export function formatDateTime(value) {
  const date = new Date(value);
  if (typeof value !== "string" || Number.isNaN(date.valueOf())) return null;
  return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit" }).format(date);
}
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
// 月数を足した日。移動先の月にない日（11/30の3か月後など）は月末にする。
export function addMonths(value, months) {
  const [year, month, day] = value.split("-").map(Number);
  const last = new Date(Date.UTC(year, month + months, 0)).getUTCDate();
  return dateKey(new Date(Date.UTC(year, month - 1 + months, Math.min(day, last))));
}
