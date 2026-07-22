import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, formatApiError } from "@/lib/api";

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  // null = checking, false = anonymous, object = authenticated
  const [user, setUser] = useState(null);

  const bootstrap = useCallback(async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      setUser(false);
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const login = async ({ email, password, captcha_token }) => {
    const { data } = await api.post("/auth/login", { email, password, captcha_token });
    if (data.access_token) localStorage.setItem("ic_token", data.access_token);
    setUser(data.user);
    return data.user;
  };

  const register = async ({ email, password, name, captcha_token }) => {
    const { data } = await api.post("/auth/register", { email, password, name, captcha_token });
    if (data.access_token) localStorage.setItem("ic_token", data.access_token);
    setUser(data.user);
    return data.user;
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("ic_token");
    setUser(false);
  };

  return (
    <AuthCtx.Provider value={{ user, login, register, logout, refresh: bootstrap, formatApiError }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be inside <AuthProvider>");
  return ctx;
}
