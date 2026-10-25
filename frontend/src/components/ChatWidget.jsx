import { useEffect } from "react";
import { useChatConfig } from "../hooks/useChatConfig";

export default function ChatWidget() {
  const cfg = useChatConfig();
  if (!cfg?.enabled || !cfg?.widget_id) return null;

  useEffect(() => {
    // inject Chatwoot SDK script once
    const script = document.createElement("script");
    script.src = `${cfg.api_base}/packs/js/sdk.js`;
    script.async = true;
    script.dataset.websiteToken = cfg.widget_id;
    script.dataset.baseUrl = cfg.api_base;
    document.body.appendChild(script);

    script.onload = () => {
      if (window.chatwootSettings) return;
      window.chatwootSettings = {
        websiteToken: cfg.widget_id,
        baseUrl: cfg.api_base,
      };
    };

    return () => {
      script.remove();
      delete window.chatwootSettings;
    };
  }, [cfg.enabled, cfg.widget_id, cfg.api_base]);

  return null;
}