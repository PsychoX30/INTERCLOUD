import { useEffect, useState } from "react";
import { api } from "../portal/api";

export function useJitsiConfig() {
  const [cfg, setCfg] = useState({
    enabled: false,
    domain: "meet.intercloud-digital.com",
    default_room_prefix: "intercloud",
    jwt_secret: "",
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.get("/jitsi/config")
      .then(({ data }) => { if (!cancelled) setCfg(data); })
      .catch(() => { /* keep defaults */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { ...cfg, loading };
}