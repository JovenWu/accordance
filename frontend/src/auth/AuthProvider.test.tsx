import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./auth-context";

afterEach(() => vi.restoreAllMocks());

function stubMe(ok: boolean, isAdmin = false) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok, status: ok ? 200 : 401,
    json: async () => ({ username: "alice", is_admin: isAdmin }),
    text: async () => "err",
  })));
}

describe("AuthProvider", () => {
  it("shows the app when /me succeeds", async () => {
    stubMe(true);
    render(<AuthProvider><div>SECRET APP</div></AuthProvider>);
    await waitFor(() => expect(screen.getByText("SECRET APP")).toBeInTheDocument());
  });

  it("shows the login form when /me is 401", async () => {
    stubMe(false);
    render(<AuthProvider><div>SECRET APP</div></AuthProvider>);
    await waitFor(() =>
      expect(screen.getByLabelText(/username/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText("SECRET APP")).not.toBeInTheDocument();
  });

  it("exposes isAdmin from /me", async () => {
    stubMe(true, true);
    function Probe() {
      const { isAdmin } = useAuth();
      return <div>{isAdmin ? "ADMIN" : "USER"}</div>;
    }
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByText("ADMIN")).toBeInTheDocument());
  });
});
