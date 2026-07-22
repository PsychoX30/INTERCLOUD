import React from "react";
import { useLang } from "../i18n/LanguageContext";

/**
 * Segmented pill toggle: ID / EN.
 * Variant "dark" (default) is for placement on dark navy backgrounds (header).
 * Variant "light" is for placement on light backgrounds.
 */
export const LanguageToggle = ({ variant = "dark", className = "" }) => {
  const { lang, setLang, t } = useLang();
  const isDark = variant === "dark";

  const base =
    "inline-flex items-center rounded-full p-1 border transition-colors";
  const wrap = isDark
    ? "bg-white/10 border-white/15"
    : "bg-white border-slate-200";

  const btn = (active) => {
    const activeCls = "bg-[#f5b120] text-[#0a2350] shadow-sm";
    const inactiveCls = isDark
      ? "text-white/70 hover:text-white"
      : "text-slate-500 hover:text-[#0a2350]";
    return `px-3 py-1.5 rounded-full text-xs font-bold tracking-wider transition-colors ${
      active ? activeCls : inactiveCls
    }`;
  };

  return (
    <div
      className={`${base} ${wrap} ${className}`}
      role="group"
      aria-label={t("lang.toggle.aria")}
      data-testid="lang-toggle"
    >
      <button
        type="button"
        onClick={() => setLang("id")}
        aria-pressed={lang === "id"}
        data-testid="lang-toggle-id"
        className={btn(lang === "id")}
      >
        ID
      </button>
      <button
        type="button"
        onClick={() => setLang("en")}
        aria-pressed={lang === "en"}
        data-testid="lang-toggle-en"
        className={btn(lang === "en")}
      >
        EN
      </button>
    </div>
  );
};

export default LanguageToggle;
