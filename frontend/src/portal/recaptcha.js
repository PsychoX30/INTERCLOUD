/**
 * Google reCAPTCHA v3 helper - vanilla script loader + token executor.
 *
 * Pulls config from `GET /api/portal/auth/config` on first use, caches it,
 * lazily injects Google's script, and returns a fresh token for the given
 * action ("login", "register", "forgot"). When reCAPTCHA is disabled on the
 * server it resolves to `null` so callers can pass the payload through unchanged.
 */
import { api } from "./api";

let _configPromise = null;
let _scriptPromise = null;
let _cachedSiteKey = null;

async function fetchConfig() {
  if (_configPromise) return _configPromise;
  _configPromise = api.get("/auth/config").then(
    (r) => r.data?.recaptcha || { enabled: false, site_key: null }
  ).catch(() => ({ enabled: false, site_key: null }));
  return _configPromise;
}

function loadScript(siteKey) {
  if (typeof window === "undefined") return Promise.resolve();
  if (window.grecaptcha && window.grecaptcha.execute) return Promise.resolve();
  if (_scriptPromise && _cachedSiteKey === siteKey) return _scriptPromise;

  _cachedSiteKey = siteKey;
  _scriptPromise = new Promise((resolve, reject) => {
    const id = "recaptcha-v3-script";
    const existing = document.getElementById(id);
    if (existing) {
      if (window.grecaptcha) return resolve();
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("Failed to load reCAPTCHA")));
      return;
    }
    const s = document.createElement("script");
    s.id = id;
    s.src = `https://www.google.com/recaptcha/api.js?render=${encodeURIComponent(siteKey)}`;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Failed to load reCAPTCHA"));
    document.head.appendChild(s);
  });
  return _scriptPromise;
}

/** Poll until the grecaptcha object is fully initialised (execute available).
 * Right after script onload, `grecaptcha` exists but `.execute` is attached
 * asynchronously - checking it immediately made the FIRST login always fail. */
function waitForGrecaptcha(timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    (function poll() {
      const g = typeof window !== "undefined" ? window.grecaptcha : null;
      if (g && typeof g.ready === "function") return resolve(g);
      if (Date.now() - started > timeoutMs) return reject(new Error("reCAPTCHA not ready"));
      setTimeout(poll, 100);
    })();
  });
}

/** Returns a token or null if reCAPTCHA is disabled server-side. */
export async function getRecaptchaToken(action) {
  const cfg = await fetchConfig();
  if (!cfg?.enabled || !cfg.site_key) return null;
  await loadScript(cfg.site_key);
  const g = await waitForGrecaptcha();
  return new Promise((resolve, reject) => {
    g.ready(() => {
      g.execute(cfg.site_key, { action }).then(resolve).catch(reject);
    });
  });
}

/** Warm up config + Google script so the token is instant on first submit. */
export async function preloadRecaptcha() {
  try {
    const cfg = await fetchConfig();
    if (cfg?.enabled && cfg.site_key) {
      await loadScript(cfg.site_key);
      await waitForGrecaptcha().catch(() => null);
    }
    return !!cfg?.enabled;
  } catch {
    return false;
  }
}

/** Public helper for pages that want to render a "Protected by reCAPTCHA" note. */
export async function isRecaptchaEnabled() {
  const cfg = await fetchConfig();
  return !!cfg?.enabled;
}

/** Reset internal caches (used by tests / after admin toggles the integration). */
export function _resetRecaptchaCache() {
  _configPromise = null;
  _scriptPromise = null;
  _cachedSiteKey = null;
}
