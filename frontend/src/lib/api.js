import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL || "";
export const API_URL = `${BASE}/api`;

export const api = axios.create({
  baseURL: API_URL,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Attach bearer token fallback (in case cookies get stripped by proxy)
api.interceptors.request.use((config) => {
  const t = localStorage.getItem("ic_token");
  if (t && !config.headers?.Authorization) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${t}`;
  }
  return config;
});

export function formatApiError(detail) {
  if (detail == null) return "Terjadi kesalahan. Silakan coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
