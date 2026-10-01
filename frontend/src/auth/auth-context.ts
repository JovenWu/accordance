import { createContext, useContext } from "react";

export interface AuthValue {
  username: string;
  isAdmin: boolean;
  logout: () => Promise<void>;
}
export const AuthContext = createContext<AuthValue | null>(null);

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}
