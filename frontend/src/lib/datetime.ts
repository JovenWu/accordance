// The app shows all timestamps in UTC+7 (WIB). The backend stores SQLite
// CURRENT_TIMESTAMP, which is UTC, and serializes it WITHOUT a timezone marker
// (e.g. "2026-06-24T02:30:00" or "2026-06-24 02:30:00"). A zone-less value must
// therefore be interpreted as UTC — otherwise the browser parses it as local
// time and the displayed clock is wrong.
const TIME_ZONE = "Asia/Jakarta";

/** Parse an API timestamp, treating a zone-less value as UTC. */
export function parseServerDate(iso: string): Date {
  const s = iso.includes("T") ? iso : iso.replace(" ", "T");
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(s);
  // Only stamp UTC when there's a time component; a date-only value is already
  // treated as UTC by the spec.
  const needsUtc = !hasZone && /T\d/.test(s);
  return new Date(needsUtc ? `${s}Z` : s);
}

/**
 * Format an API timestamp in UTC+7 (Asia/Jakarta), in the viewer's locale.
 * Returns the raw string unchanged if it can't be parsed.
 */
export function formatDateTime(
  iso: string,
  opts?: Intl.DateTimeFormatOptions,
): string {
  const d = parseServerDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { timeZone: TIME_ZONE, ...opts });
}
