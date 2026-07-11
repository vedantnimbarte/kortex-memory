import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, login as apiLogin, logout as apiLogout, register as apiRegister, tokens } from "./api";
import type { Whoami } from "./types";

type AuthState = {
  user: Whoami | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, orgName: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Whoami | null>(null);
  const [loading, setLoading] = useState(true);

  async function bootstrap() {
    if (!tokens.access) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api<Whoami>("/v1/auth/whoami"));
    } catch {
      tokens.clear();
      setUser(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void bootstrap();
  }, []);

  const value: AuthState = {
    user,
    loading,
    async login(email, password) {
      await apiLogin(email, password);
      setUser(await api<Whoami>("/v1/auth/whoami"));
    },
    async signup(email, password, orgName) {
      await apiRegister(email, password, orgName);
      setUser(await api<Whoami>("/v1/auth/whoami"));
    },
    async logout() {
      await apiLogout();
      setUser(null);
    },
    async refreshUser() {
      setUser(await api<Whoami>("/v1/auth/whoami"));
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
