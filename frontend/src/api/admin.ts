import type { AdminUser, AdminUserDetail } from "../types";
import { http, postJson, request, requestVoid } from "./http";

export const adminListUsers = () => http<AdminUser[]>("/admin/users");
export const adminGetUser = (id: number) =>
  http<AdminUserDetail>(`/admin/users/${id}`);

export const adminCreateUser = (username: string, password: string) =>
  postJson<AdminUser>("/admin/users", { username, password });

export const adminSetActive = (id: number, isActive: boolean) =>
  request<AdminUser>(`/admin/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: isActive }),
  });

export const adminSetAdmin = (id: number, isAdmin: boolean) =>
  request<AdminUser>(`/admin/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_admin: isAdmin }),
  });

export const adminResetPassword = (id: number, password: string) =>
  requestVoid(`/admin/users/${id}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
