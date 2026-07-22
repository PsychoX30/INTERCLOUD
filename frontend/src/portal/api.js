import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
const TOKEN_KEY = "ic_portal_token";

export const api = axios.create({
  baseURL: `${BASE}/api/portal`,
});

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      if (!window.location.pathname.startsWith("/portal/login")) {
        window.location.href = "/portal/login?expired=1";
      }
    }
    return Promise.reject(err);
  }
);

export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);
export const getToken = () => localStorage.getItem(TOKEN_KEY);

export const docUrl = (kind, id, format = "html") => {
  const t = getToken();
  const params = new URLSearchParams();
  params.set("token", t || "");
  if (format === "pdf") params.set("format", "pdf");
  return `${BASE}/api/portal/documents/${kind}/${id}?${params.toString()}`;
};

export const formatApiError = (err) => {
  const d = err?.response?.data?.detail;
  if (d == null) return err?.message || "Unknown error";
  if (typeof d === "string") return d;
  if (Array.isArray(d))
    return d
      .map((e) => (e?.msg ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  return typeof d === "object" ? d.msg || JSON.stringify(d) : String(d);
};

export const money = (v) =>
  new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0,
  }).format(v || 0);

export const shortDate = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("id-ID", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
};

export const fullDateTime = (iso) => {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("id-ID", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};
