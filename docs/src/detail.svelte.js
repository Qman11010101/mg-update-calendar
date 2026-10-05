// 詳細ダイアログに表示する項目。項目は表示時に entry.family を書き換えるため、プロキシにしない。
class Detail {
  item = $state.raw(null);
}
export const detail = new Detail();

export function openItem(item) { detail.item = item; }
