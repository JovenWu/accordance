import { afterEach, describe, expect, it, vi } from "vitest";

import { deleteCorrection, deleteRun } from "./runs";
import { deleteReport } from "./reports";

afterEach(() => vi.restoreAllMocks());

function stubFetch(ok: boolean, status = ok ? 200 : 500) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok,
      status,
      text: async () => "boom",
      json: async () => ({}),
    })),
  );
}

describe("destructive delete helpers surface failures", () => {
  it("deleteRun rejects on a non-ok response", async () => {
    stubFetch(false, 500);
    await expect(deleteRun("r1")).rejects.toThrow();
  });

  it("deleteRun resolves to void on success", async () => {
    stubFetch(true);
    await expect(deleteRun("r1")).resolves.toBeUndefined();
  });

  it("deleteReport rejects on a non-ok response", async () => {
    stubFetch(false, 404);
    await expect(deleteReport("rep1")).rejects.toThrow();
  });

  it("deleteCorrection rejects on a non-ok response", async () => {
    stubFetch(false, 500);
    await expect(deleteCorrection("r1", 7)).rejects.toThrow();
  });
});
