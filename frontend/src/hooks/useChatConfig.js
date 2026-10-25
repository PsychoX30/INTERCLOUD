import { useEffect, useState } from "react";
import { api } from "../portal/api";

export function useChatConfig() {
  const [cfg, setCfg] = useState(null);
  useEffect(() => {
    api.get("/chat/config")
      .then(({ data }) => setCfg(data))
      .catch(() => setCfg({ enabled: false, widget_id: "", api_base: "" }));
  }, []);
  return cfg;
}