const TIME_ZONE = "Asia/Jakarta";

export function parseServerDate(iso: string): Date {
  const s = iso.includes("T") ? iso : iso.replace(" ", "T");
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(s);
  const needsUtc = !hasZone && /T\d/.test(s);
  return new Date(needsUtc ? `${s}Z` : s);
}

export function formatDateTime(
  iso: string,
  opts?: Intl.DateTimeFormatOptions,
): string {
  const d = parseServerDate(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { timeZone: TIME_ZONE, ...opts });
}
