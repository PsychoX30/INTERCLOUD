import { useEffect, useRef } from "react";

/**
 * Cloudflare Turnstile CAPTCHA placeholder.
 * Renders only when REACT_APP_TURNSTILE_ENABLED=true AND a site key is provided.
 * When disabled, shows a compact "disabled" banner so users know the slot exists.
 */
export default function TurnstileWidget({ onToken }) {
  const ref = useRef(null);
  const enabled =
    (process.env.REACT_APP_TURNSTILE_ENABLED || "false").toLowerCase() === "true";
  const siteKey = process.env.REACT_APP_TURNSTILE_SITE_KEY || "";

  useEffect(() => {
    if (!enabled || !siteKey) return;
    // Inject Turnstile script once
    const id = "cf-turnstile-script";
    let script = document.getElementById(id);
    if (!script) {
      script = document.createElement("script");
      script.id = id;
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
    const render = () => {
      if (window.turnstile && ref.current && !ref.current.dataset.rendered) {
        window.turnstile.render(ref.current, {
          sitekey: siteKey,
          callback: (token) => onToken?.(token),
          "error-callback": () => onToken?.(""),
          "expired-callback": () => onToken?.(""),
        });
        ref.current.dataset.rendered = "true";
      }
    };
    if (window.turnstile) render();
    else script.addEventListener("load", render);
    return () => script?.removeEventListener("load", render);
  }, [enabled, siteKey, onToken]);

  if (!enabled) {
    return (
      <div
        data-testid="captcha-placeholder"
        className="mt-2 rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-500"
      >
        CAPTCHA slot • Cloudflare Turnstile (disabled)
      </div>
    );
  }
  return <div data-testid="captcha-widget" ref={ref} className="mt-2" />;
}
