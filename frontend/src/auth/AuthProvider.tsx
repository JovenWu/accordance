import { useCallback, useEffect, useState } from "react";

import {
  getMe,
  login as apiLogin,
  logout as apiLogout,
  setOnUnauthorized,
} from "@/api";
import { LoginPage } from "@/pages/LoginPage";
import { AuthContext } from "./auth-context";

type Status = "loading" | "in" | "out";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [username, setUsername] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setUsername(me.username);
      setIsAdmin(me.is_admin);
      setStatus("in");
    } catch {
      setStatus("out");
    }
  }, []);

  useEffect(() => {
    setOnUnauthorized(() => setStatus("out"));
    void refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await apiLogout();
    setStatus("out");
  }, []);

  if (status === "loading") {
    return (
      <div className="grid min-h-screen place-items-center bg-page text-muted-ink">
        Loading…
      </div>
    );
  }
  if (status === "out") {
    return (
      <LoginPage
        onSubmit={async (u, p) => {
          await apiLogin(u, p);
          await refresh();
        }}
      />
    );
  }
  return (
    <AuthContext.Provider value={{ username, isAdmin, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
