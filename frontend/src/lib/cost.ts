/** Format a USD amount for display.
 *
 * Always 4 decimals: a whole report can cost well under a cent (a measured
 * 150-disclosure run came to $0.0710), so 2dp collapsed real spend to "$0.07"
 * — or "$0.00" — and made per-run figures impossible to compare.
 */
export function formatCost(usd: number): string {
  return `$${usd.toFixed(4)}`;
}

/** Abbreviate a token count so a daily column stays scannable.
 *
 * Judge runs book millions of tokens per day, and the raw digits are both
 * unreadable and irrelevant at that scale — the useful comparison is between
 * days, not the exact count. Sub-1000 stays exact so a quiet day doesn't
 * render as a misleading "0.0K".
 */
export function formatTokens(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "0";
  if (n < 1_000) return String(Math.round(n));
  if (n < 1_000_000) return `${(n / 1_000).toFixed(1)}K`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}
