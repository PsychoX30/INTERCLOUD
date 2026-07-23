import React, { useState } from "react";
import { Menu, X, Phone, LogIn } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";
import LanguageToggle from "./LanguageToggle";
import useBranding from "../hooks/useBranding";

const Logo = () => {
  const branding = useBranding();
  return (
    <Link to="/" className="flex items-center gap-3" data-testid="site-logo-link">
      {branding.logo_light ? (
        <img
          src={branding.logo_light}
          alt="Intercloud Digital Inovasi"
          className="h-11 md:h-12 w-auto object-contain"
          loading="eager"
          data-testid="site-logo-img"
        />
      ) : (
        <span className="text-white font-extrabold text-lg tracking-tight" data-testid="site-logo-fallback">INTERCLOUD</span>
      )}
    </Link>
  );
};

const Header = () => {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const { lang, t } = useLang();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const onLanding = pathname === "/";

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const NAV_LINKS = [
    { key: "nav.home",     hash: "home" },
    { key: "nav.why",      hash: "why" },
    { key: "nav.services", hash: "services" },
    { key: "nav.pricing",  hash: "pricing" },
    { key: "nav.faq",      hash: "faq" },
    { key: "nav.contact",  hash: "contact" },
  ];

  // Anchor click handler: if we're already on the landing page, prevent the
  // full navigation and just scrollIntoView (smooth). Otherwise let the
  // router navigate to /#hash — ScrollToTop will handle the scroll on mount.
  const goToSection = (hash, e) => {
    if (onLanding) {
      e.preventDefault();
      const el = document.getElementById(hash);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      setOpen(false);
      return;
    }
    // Cross-page nav: use router so we don't do a full page reload.
    e.preventDefault();
    setOpen(false);
    navigate({ pathname: "/", hash: `#${hash}` });
  };

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
              key={l.hash}
              href={`/#${l.hash}`}
              onClick={(e) => goToSection(l.hash, e)}
              className="text-white/80 hover:text-[#f5b120] text-sm font-medium transition-colors"
              data-testid={`nav-${l.hash}`}
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
                key={l.hash}
                href={`/#${l.hash}`}
                onClick={(e) => goToSection(l.hash, e)}
                className="text-white/90 hover:text-[#f5b120] text-sm font-medium"
                data-testid={`mobile-nav-${l.hash}`}
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
