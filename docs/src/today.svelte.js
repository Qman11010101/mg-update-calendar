// 画面が使う「今日」（Asia/Tokyo の YYYY-MM-DD）。タブを開いたまま日付をまたいでも更新できる。
import { tokyoDate } from "../lib/dates.js";

class Today {
  date = $state(tokyoDate());

  // 日付が変わっていれば更新し、変わったときだけ true を返す。
  refresh(now = new Date()) {
    const next = tokyoDate(now);
    if (next === this.date) return false;
    this.date = next;
    return true;
  }
}

export const today = new Today();
