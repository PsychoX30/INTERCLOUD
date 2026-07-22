import React, { useState } from "react";
import { Menu, X, Phone, LogIn } from "lucide-react";
import { Link } from "react-router-dom";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";
import LanguageToggle from "./LanguageToggle";

const Logo = () => (
  <Link to="/" className="flex items-center gap-3" data-testid="site-logo-link">
    <img
      src="https://intercloud-digital.com/wp-content/uploads/2024/07/Mask-group.png"
      alt="Intercloud Digital Inovasi"
      className="h-11 md:h-12 w-auto object-contain"
      loading="eager"
      data-testid="site-logo-img"
    />
  </Link>
);

const Header = () => {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const { lang, t } = useLang();

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const NAV_LINKS = [
    { key: "nav.home", href: "#home" },
    { key: "nav.why", href: "#why" },
    { key: "nav.services", href: "#services" },
    { key: "nav.pricing", href: "#pricing" },
    { key: "nav.faq", href: "#faq" },
    { key: "nav.contact", href: "#contact" },
  ];

  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;

  return (
    <header
      className={`fixed top-0 inset-x-0 z-40 transition-colors duration-300 ${
        scrolled ? "bg-[#061b3a]/95 backdrop-blur border-b border-white/10" : "bg-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-5 lg:px-8 flex items-center justify-between h-[74px]">
        <Logo />
        <nav className="hidden lg:flex items-center gap-7">
          {NAV_LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="text-white/80 hover:text-[#f5b120] text-sm font-medium transition-colors"
            >
              {t(l.key)}
            </a>
          ))}
          <Link
            to="/articles"
            className="text-white/80 hover:text-[#f5b120] text-sm font-medium transition-colors"
            data-testid="header-articles-link"
          >
            {lang === "en" ? "Articles" : "Artikel"}
          </Link>
        </nav>
        <div className="hidden lg:flex items-center gap-3">
          <LanguageToggle variant="dark" />
          <Link
            to="/portal/login"
            data-testid="header-portal-link"
            className="inline-flex items-center gap-1.5 text-white/85 hover:text-[#f5b120] text-sm font-semibold transition-colors"
          >
            <LogIn className="h-4 w-4" /> {lang === "en" ? "Client Portal" : "Portal Klien"}
          </Link>
          <a
            href={waLink}
            target="_blank"
            rel="noreferrer"
            data-testid="header-contact-cta"
            className="inline-flex items-center gap-2 rounded-full bg-[#f5b120] hover:bg-[#ffc94a] text-[#0a2350] px-5 py-2.5 text-sm font-semibold transition-colors"
          >
            <Phone className="h-4 w-4" />
            {t("cta.contactUs")}
          </a>
        </div>
        <div className="lg:hidden flex items-center gap-2">
          <LanguageToggle variant="dark" />
          <button
            className="text-white p-2"
            onClick={() => setOpen((v) => !v)}
            aria-label="menu"
            data-testid="mobile-menu-toggle"
          >
            {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>
      </div>

      {open && (
        <div className="lg:hidden bg-[#061b3a] border-t border-white/10" data-testid="mobile-menu">
          <div className="px-5 py-4 flex flex-col gap-4">
            {NAV_LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className="text-white/90 hover:text-[#f5b120] text-sm font-medium"
              >
                {t(l.key)}
              </a>
            ))}
            <Link
              to="/articles"
              onClick={() => setOpen(false)}
              className="text-white/90 hover:text-[#f5b120] text-sm font-medium"
              data-testid="mobile-articles-link"
            >
              {lang === "en" ? "Articles" : "Artikel"}
            </Link>
            <Link
              to="/portal/login"
              onClick={() => setOpen(false)}
              className="mt-2 inline-flex items-center justify-center gap-2 rounded-full border border-white/20 text-white/90 px-5 py-2.5 text-sm font-semibold"
            >
              <LogIn className="h-4 w-4" /> {lang === "en" ? "Client Portal" : "Portal Klien"}
            </Link>
            <a
              href={waLink}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-center gap-2 rounded-full bg-[#f5b120] text-[#0a2350] px-5 py-2.5 text-sm font-semibold"
            >
              <Phone className="h-4 w-4" /> {t("cta.contactUs")}
            </a>
          </div>
        </div>
      )}
    </header>
  );
};

export default Header;
