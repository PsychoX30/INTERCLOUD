import { useEffect, useState } from "react";
import { api } from "../portal/api";

/**
 * Config Jitsi publik. Backend TIDAK pernah mengirim `jwt_secret`
 * (hanya flag `jwt_secret_set`), jadi hook ini tidak menyimpannya di state.
 */
export function useJitsiConfig() {
  const [cfg, setCfg] = useState({
    enabled: false,
    domain: "meet.intercloud-digital.com",
    default_room_prefix: "intercloud",
    jwt_secret_set: false,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    api.get("/jitsi/config")
      .then(({ data }) => {
        if (cancelled) return;
        const { jwt_secret, ...safe } = data || {};
        setCfg((prev) => ({ ...prev, ...safe }));
      })
      .catch(() => { /* keep defaults */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { ...cfg, loading };
}