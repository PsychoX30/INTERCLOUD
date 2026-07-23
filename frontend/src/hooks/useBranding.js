import { useEffect, useState, useMemo } from "react";
import axios from "axios";

/**
 * Portal-wide branding hook. Fetches /api/portal/branding once and caches
 * the result in module scope so the second, third, Nth mount all read
 * from memory. Public endpoint — no auth needed.
 *
 * Returns a derived object:
 *   {
 *     logo_dark,          // navy artwork — invoice/PDF/email/white surfaces
 *     logo_light,         // white artwork for dark surfaces
 *     logo_light_source,  // "uploaded" if admin uploaded a bespoke variant,
 *                         // "inverted" if we auto-derived from logo_dark
 *     favicon,
 *     email_banner,
 *   }
 *
 * The `logo_light_source` flag lets the consumer decide whether to apply
 * `filter: brightness(0) invert(1)` when rendering. That filter turns a
 * dark-coloured image into a white silhouette, which is exactly what
 * operators want when they upload a single dark-on-white logo and expect
 * it to work over both light and dark backgrounds.
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
  const [raw, setRaw] = useState(_cache || {
    logo_light: "", logo_dark: "", favicon: "", email_banner: "",
  });

  useEffect(() => {
    let cancelled = false;
    fetchBranding().then((b) => { if (!cancelled) setRaw(b); });
    return () => { cancelled = true; };
  }, []);

  return useMemo(() => {
    const hasUploadedLight = !!raw.logo_light;
    return {
      ...raw,
      logo_light: raw.logo_light || raw.logo_dark || "",
      logo_light_source: hasUploadedLight ? "uploaded" : "inverted",
    };
  }, [raw]);
}
