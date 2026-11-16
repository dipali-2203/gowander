import { createContext, useContext } from "react";
import type { AuthUser } from "@/lib/api";

export type AuthContextValue = {
  user: AuthUser;
  setUser: (user: AuthUser) => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth() {
  return useContext(AuthContext);
}
