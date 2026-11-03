export function formatMoney(value: number) { return new Intl.NumberFormat("ja-JP", { style: "currency", currency: "JPY", maximumFractionDigits: 0 }).format(value).replace("￥", "¥"); }
const day = (value: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).format(value);
export function formatDateTime(value: string | null | undefined, now = new Date()) {
  if (!value) return "—";
  const date = new Date(value); if (Number.isNaN(date.getTime())) return "—";
  const time = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
  const parts = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric" }).formatToParts(date);
  const prefix = day(date) === day(now) ? "本日" : `${parts.find(part => part.type === "month")?.value}月${parts.find(part => part.type === "day")?.value}日`;
  return `${prefix} ${time}`;
}
export function formatTime(value: string | null | undefined) { if (!value) return "—"; return new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value)); }
