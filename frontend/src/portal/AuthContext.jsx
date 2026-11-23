import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api, setToken, clearToken, getToken, formatApiError } from "./api";
import { getRecaptchaToken } from "./recaptcha";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(undefined); // undefined = checking, null = logged out
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch {
      clearToken();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(async (email, password) => {
    setError(null);
    try {
      const recaptcha_token = await getRecaptchaToken("login").catch(() => null);
      const { data } = await api.post("/auth/login", { email, password, recaptcha_token });
      if (data.require_2fa) return { require_2fa: true, mfa_token: data.mfa_token };
      setToken(data.token);
      setUser(data.user);
      return data.user;
    } catch (e) {
      const msg = formatApiError(e);
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const loginTwoFA = useCallback(async (mfaToken, code) => {
    setError(null);
    try {
      const { data } = await api.post("/auth/login/2fa", { mfa_token: mfaToken, code });
      setToken(data.token);
      setUser(data.user);
      return data.user;
    } catch (e) {
      const msg = formatApiError(e);
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const register = useCallback(async (payload) => {
    setError(null);
    try {
      const recaptcha_token = await getRecaptchaToken("register").catch(() => null);
      const { data } = await api.post("/auth/register", { ...payload, recaptcha_token });
      setToken(data.token);
      setUser(data.user);
      return data.user;
    } catch (e) {
      const msg = formatApiError(e);
      setError(msg);
      throw new Error(msg);
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    window.location.href = "/portal/login";
  }, []);

  /* Capability check for the UI. The backend enforces the same list
   * (`effective_feature_flags` is computed server-side from the role defaults or
   * the account's override), so a hidden button and a refused request always
   * agree. Admin bypasses flags, matching `require_flag`.
   *
   * Purely cosmetic: never rely on this for security, only to avoid showing
   * actions the API will reject.
   */
  const hasFlag = useCallback((key) => {
    if (!key) return true;
    if (user?.role === "admin") return true;
    const granted = user?.effective_feature_flags || user?.feature_flags || [];
    return granted.includes(key);
  }, [user]);

  return (
    <AuthContext.Provider value={{ user, error, login, loginTwoFA, register, logout, refresh, hasFlag }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
