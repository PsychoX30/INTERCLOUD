import { useEffect, useState } from "react";
import axios from "axios";

/**
 * Portal-wide branding hook. Fetches /api/portal/branding once and caches
 * the result in module scope so the second, third, Nth mount all read
 * from memory. Public endpoint — no auth needed.
 *
 * Returns the merged {defaults, DB overrides} shape:
 *   { logo_light, logo_dark, favicon, email_banner }
 *
 * While the first fetch is in flight `logo_light` / `logo_dark` are
 * empty strings so consumers can skip rendering to avoid a broken-image
 * flash. Once loaded, defaults from backend/portal/branding.py fill in
 * (inline SVG data URIs — always renderable, no external dependency).
 */

let _cache = null;
let _inflight = null;

const BASE = process.env.REACT_APP_BACKEND_URL;

async function fetchBranding() {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = axios
    .get(`${BASE}/api/portal/branding`)
    .then((r) => {
      _cache = r.data || {};
      return _cache;
    })
    .catch(() => ({ logo_light: "", logo_dark: "", favicon: "", email_banner: "" }))
    .finally(() => { _inflight = null; });
  return _inflight;
}

export function invalidateBrandingCache() {
  _cache = null;
}

export default function useBranding() {
  const [branding, setBranding] = useState(_cache || {
    logo_light: "", logo_dark: "", favicon: "", email_banner: "",
  });

  useEffect(() => {
    let cancelled = false;
    fetchBranding().then((b) => { if (!cancelled) setBranding(b); });
    return () => { cancelled = true; };
  }, []);

  return branding;
}
