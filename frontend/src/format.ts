const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const p2 = (n: number) => String(n).padStart(2, '0');

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${p2(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}Z`;
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return `${p2(d.getUTCDate())} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
export const pct = (x: number | null | undefined) => (x == null ? '-' : `${Math.round(x * 100)}%`);
export const short = (h: string, n = 12) => (h.length > n ? `${h.slice(0, n)}...` : h);
export const titleCase = (s: string) => s.replace(/[_.-]/g, ' ').replace(/^./, (c) => c.toUpperCase());
export function relDays(fromIso: string, nowIso: string): string {
  const d = Math.floor((Date.parse(nowIso) - Date.parse(fromIso)) / 86400000);
  return d <= 0 ? 'today' : `${d}d ago`;
}
