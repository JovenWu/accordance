import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { adminCreateUser, adminListUsers, adminSetActive } from "./admin";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function ok(body: unknown) {
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

const sampleUser = {
  id: 1,
  username: "a",
  is_admin: true,
  is_active: true,
  created_at: "2026-06-26T00:00:00",
  pdf_count: 0,
  cost_usd: 0,
};

describe("admin client", () => {
  it("lists users via GET", async () => {
    ok([sampleUser]);
    const users = await adminListUsers();
    expect(users[0].username).toBe("a");
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/users", undefined);
  });

  it("creates a user via POST", async () => {
    ok(sampleUser);
    await adminCreateUser("b", "password1");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/users");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ username: "b", password: "password1" });
  });

  it("sets active via PATCH", async () => {
    ok({ ...sampleUser, is_active: false });
    await adminSetActive(1, false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/users/1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ is_active: false });
  });

  it("fetches a user detail via GET", async () => {
    const detail = { ...sampleUser, last_active: null, cost_by_kind: [], recent_runs: [] };
    ok(detail);
    const { adminGetUser } = await import("./admin");
    const got = await adminGetUser(1);
    expect(got.username).toBe("a");
    expect(fetchMock).toHaveBeenCalledWith("/api/admin/users/1", undefined);
  });

  it("sets admin via PATCH", async () => {
    ok({ ...sampleUser, is_admin: false });
    const { adminSetAdmin } = await import("./admin");
    await adminSetAdmin(1, false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/users/1");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ is_admin: false });
  });

  it("resets a password via POST (no body parse on 204)", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204, text: async () => "" });
    const { adminResetPassword } = await import("./admin");
    await adminResetPassword(7, "newpass99");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/users/7/reset-password");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ password: "newpass99" });
  });
});
