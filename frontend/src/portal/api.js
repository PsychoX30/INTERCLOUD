import axios from "axios";

const BASE = process.env.REACT_APP_BACKEND_URL;
const TOKEN_KEY = "ic_portal_token";

// A request must always settle.
//
// Measured on 2026-11-25: the kernel OOM-killed a backend worker while a page was
// loading. nginx answered 502 for a while, then nothing at all. A request to a
// process that is gone, or to a socket nobody closes, does not fail fast — the
// browser holds it until its own socket timeout, which is minutes. Every page
// waiting on it showed a spinner for that whole time. A timeout converts that
// into an ordinary rejection the UI can render.
export const REQUEST_TIMEOUT_MS = 20000;

// How long a spinner is allowed to spin before the UI says something. Shorter
// than the request timeout on purpose: the point is to speak before the network
// gives up, not after.
export const SLOW_REQUEST_MS = 15000;

export const api = axios.create({
  baseURL: `${BASE}/api/portal`,
  timeout: REQUEST_TIMEOUT_MS,
});

// App-wide "is the API answering" signal, derived from real responses rather
// than from a health poll (which would be one more request per page, and would
// itself hang on the failure it is meant to detect).
let _backendDown = false;

export const isBackendDown = () => _backendDown;

export const onBackendState = (cb) => {
  const down = () => cb(true);
  const up = () => cb(false);
  window.addEventListener("ic-backend-down", down);
  window.addEventListener("ic-backend-up", up);
  return () => {
    window.removeEventListener("ic-backend-down", down);
    window.removeEventListener("ic-backend-up", up);
  };
};

const setBackendDown = (next) => {
  if (_backendDown === next) return; // only announce transitions
  _backendDown = next;
  try {
    window.dispatchEvent(new Event(next ? "ic-backend-down" : "ic-backend-up"));
  } catch {
    /* non-browser contexts (tests) simply get no event */
  }
};

// A gateway status means the API is not answering at all. A network error with
// no response means the same thing. A 4xx/5xx that carries a Response does not:
// those are the API answering, and belong to the page that asked.
export const isGatewayFailure = (err) => {
  const status = err?.response?.status;
  if (status === 502 || status === 503 || status === 504) return true;
  if (err?.code === "ECONNABORTED" || err?.code === "ETIMEDOUT") return true;
  return !err?.response;
};

api.interceptors.request.use((cfg) => {
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

api.interceptors.response.use(
  (r) => {
    setBackendDown(false);
    return r;
  },
  (err) => {
    // FastAPI returns Pydantic validation errors as `detail` being an ARRAY of
    // objects ({type, loc, msg, input, ctx, url}) or a plain object, not a
    // string. Many components render `e?.response?.data?.detail` directly in
    // JSX, which crashes React with error #31 ("Objects are not valid as a
    // React child") and blanks the whole page. Normalize `detail` to a string
    // here so every consumer is safe.
    const data = err?.response?.data;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const d = data.detail;
      if (Array.isArray(d)) {
        data.detail = d
          .map((e) => (e && typeof e === "object" ? e.msg || JSON.stringify(e) : String(e)))
          .filter(Boolean)
          .join(" ");
      } else if (d && typeof d === "object") {
        data.detail = d.message || d.msg || JSON.stringify(d);
      }
    }
    if (err?.response?.status === 401) {
      // Public endpoints (shared folder access, password required) return 401
      // intentionally — don't redirect those to the portal login.
      if (err?.config?.headers?.["X-Skip-401-Redirect"] === "true") {
        return Promise.reject(err);
      }
      localStorage.removeItem(TOKEN_KEY);
      if (!window.location.pathname.startsWith("/portal/login")) {
        window.location.href = "/portal/login?expired=1";
      }
    } else if (isGatewayFailure(err)) {
      // Only a non-401 failure can mean "the API is gone". A 401 is the API
      // answering correctly, and must not raise the outage banner.
      setBackendDown(true);
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
  return typeof d === "object" ? d.message || d.msg || JSON.stringify(d) : String(d);
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
