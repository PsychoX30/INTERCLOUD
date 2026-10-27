import { useEffect } from "react";
import { useChatConfig } from "../hooks/useChatConfig";

export default function ChatWidget() {
  const cfg = useChatConfig();
  const enabled = !!(cfg?.enabled && cfg?.widget_id && cfg?.api_base);
  const widgetId = cfg?.widget_id;
  const apiBase = cfg?.api_base;

  useEffect(() => {
    if (!enabled || !widgetId || !apiBase) return undefined;

    const base = String(apiBase).replace(/\/+$/, "");

    // chatwootSettings MUST exist before the SDK script is evaluated
    window.chatwootSettings = window.chatwootSettings || {};
    window.chatwootSettings.baseUrl = base;
    window.chatwootSettings.websiteToken = widgetId;

    const existing = document.getElementById("chatwoot-sdk");
    if (!existing) {
      const script = document.createElement("script");
      script.id = "chatwoot-sdk";
      script.src = `${base}/packs/js/sdk.js`;
      script.async = true;
      script.defer = true;
      script.onload = () => {
        try {
          if (window.chatwootSDK?.run) {
            window.chatwootSDK.run({ websiteToken: widgetId, baseUrl: base });
          }
        } catch (err) {
          // widget gagal init: jangan sampai mematikan portal
        }
      };
      document.body.appendChild(script);
    } else if (window.chatwootSDK?.run) {
      try {
        window.chatwootSDK.run({ websiteToken: widgetId, baseUrl: base });
      } catch (err) {
        // ignore
      }
    }

    return () => {
      const el = document.getElementById("chatwoot-sdk");
      if (el) el.remove();
      try {
        delete window.chatwootSettings;
        delete window.chatwootSDK;
      } catch (err) {
        window.chatwootSettings = undefined;
        window.chatwootSDK = undefined;
      }
    };
  }, [enabled, widgetId, apiBase]);

  return null;
}
