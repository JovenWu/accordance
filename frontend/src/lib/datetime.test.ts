import { describe, expect, it } from "vitest";

import { formatDateTime, parseServerDate } from "./datetime";

describe("parseServerDate", () => {
  it("treats a zone-less datetime as UTC", () => {
    expect(parseServerDate("2026-06-24T02:30:00").toISOString()).toBe(
      "2026-06-24T02:30:00.000Z",
    );
  });
  it("handles the SQLite space separator", () => {
    expect(parseServerDate("2026-06-24 02:30:00").toISOString()).toBe(
      "2026-06-24T02:30:00.000Z",
    );
  });
  it("respects an explicit zone", () => {
    expect(parseServerDate("2026-06-24T09:30:00+07:00").toISOString()).toBe(
      "2026-06-24T02:30:00.000Z",
    );
  });
});

describe("formatDateTime", () => {
  it("renders a UTC timestamp in UTC+7 (Asia/Jakarta)", () => {
    expect(
      formatDateTime("2026-06-24T02:30:00", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    ).toMatch(/^09[.:]30$/);
  });
  it("falls back to the raw string on an unparseable value", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});
