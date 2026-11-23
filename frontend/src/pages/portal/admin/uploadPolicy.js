import { useCallback, useEffect, useState } from "react";
import { api } from "../../../portal/api";

const FALLBACK = {
  document_extensions: ["pdf", "docx", "xlsx", "pptx", "png", "jpg", "zip", "txt", "csv"],
  media_extensions: ["png", "jpg", "jpeg", "webp", "gif", "svg", "mp4", "webm", "mp3", "wav"],
  document_max_mb: 50,
  media_max_mb: 300,
  can_edit: false,
};

/** Upload policy (allowed extensions + size caps) for documents and media. */
export const useUploadPolicy = () => {
  const [policy, setPolicy] = useState(FALLBACK);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(() => {
    api.get("/admin/upload-policy")
      .then((r) => setPolicy({ ...FALLBACK, ...(r.data || {}) }))
      .catch(() => setPolicy(FALLBACK))
      .finally(() => setLoaded(true));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = useCallback(async (next) => {
    const r = await api.put("/admin/upload-policy", next);
    setPolicy({ ...FALLBACK, ...(r.data || {}) });
    return r.data;
  }, []);

  return { policy, loaded, reload, save };
};

export const acceptAttr = (exts) =>
  (exts || []).map((e) => `.${e}`).join(",");

export const parseExtInput = (text) =>
  String(text || "")
    .split(/[\s,;]+/)
    .map((e) => e.trim().toLowerCase().replace(/^\./, ""))
    .filter((e) => /^[a-z0-9]{1,12}$/.test(e));
