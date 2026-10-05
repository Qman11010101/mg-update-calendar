// 祝日は日曜と同じ見た目で扱う。
export function weekdayClass(key, weekday, holidays) {
  return weekday === 0 || holidays.has(key) ? " sunday" : weekday === 6 ? " saturday" : "";
}
