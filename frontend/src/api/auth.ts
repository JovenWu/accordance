import type { Me, MeStats } from "../types";
import { http, requestVoid } from "./http";

export function login(username: string, password: string): Promise<void> {
  return requestVoid("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export const logout = () => requestVoid("/auth/logout", { method: "POST" });

export const getMe = () => http<Me>("/auth/me");
export const getMeStats = () => http<MeStats>("/me/stats");
