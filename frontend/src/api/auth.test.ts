import { afterEach, describe, expect, it, vi } from "vitest";

import { getMe, login, logout } from "./auth";
import { setOnUnauthorized } from "./http";

afterEach(() => vi.restoreAllMocks());

function stub(ok: boolean, json: unknown = {}, status = ok ? 200 : 401) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok, status, json: async () => json, text: async () => "err",
  })));
}

describe("auth client", () => {
  it("getMe returns the user on 200", async () => {
    stub(true, { username: "alice" });
    expect(await getMe()).toEqual({ username: "alice" });
  });

  it("login rejects on bad creds", async () => {
    stub(false, {}, 401);
    await expect(login("a", "b")).rejects.toThrow();
  });

  it("logout resolves on ok", async () => {
    stub(true);
    await expect(logout()).resolves.toBeUndefined();
  });

  it("a 401 fires the onUnauthorized callback", async () => {
    const cb = vi.fn();
    setOnUnauthorized(cb);
    stub(false, {}, 401);
    await expect(getMe()).rejects.toThrow();
    expect(cb).toHaveBeenCalled();
  });
});
