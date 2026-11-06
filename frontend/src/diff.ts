export interface DiffLine { kind: 'same' | 'add' | 'del'; text: string }

/** Flatten a payload to comparable lines: one per key, multi-line strings split per line. */
export function payloadLines(p: Record<string, unknown>): string[] {
  const out: string[] = [];
  for (const k of Object.keys(p).sort()) {
    const v = p[k];
    if (typeof v === 'string' && v.includes('\n')) v.split('\n').forEach((l, i) => out.push(`${k}${i === 0 ? '' : ' (cont.)'}: ${l}`));
    else out.push(`${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
  }
  return out;
}

/** Line diff via longest common subsequence. */
export function lineDiff(a: string[], b: string[]): DiffLine[] {
  const n = a.length, m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const res: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { res.push({ kind: 'same', text: a[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) res.push({ kind: 'del', text: a[i++] });
    else res.push({ kind: 'add', text: b[j++] });
  }
  while (i < n) res.push({ kind: 'del', text: a[i++] });
  while (j < m) res.push({ kind: 'add', text: b[j++] });
  return res;
}
