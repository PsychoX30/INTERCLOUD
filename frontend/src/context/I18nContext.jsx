import { createContext, useContext, useState, useCallback } from "react";
import { DICT, pathValue } from "@/lib/i18n";

const I18nCtx = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => localStorage.getItem("ic_lang") || "id");

  const changeLang = useCallback((next) => {
    setLang(next);
    localStorage.setItem("ic_lang", next);
  }, []);

  const t = useCallback(
    (key) => {
      const val = pathValue(DICT[lang], key);
      if (val != null) return val;
      const fallback = pathValue(DICT.en, key);
      return fallback ?? key;
    },
    [lang]
  );

  return (
    <I18nCtx.Provider value={{ lang, setLang: changeLang, t }}>
      {children}
    </I18nCtx.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nCtx);
  if (!ctx) throw new Error("useI18n must be inside <I18nProvider>");
  return ctx;
}
