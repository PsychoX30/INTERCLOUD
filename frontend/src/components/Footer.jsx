import React from "react";
import { Instagram, Mail, MessageCircle, MapPin } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN, EMAIL, ADDRESS } from "../mock/data";
import { useLang, pick } from "../i18n/LanguageContext";
import useBranding from "../hooks/useBranding";

// Section anchor — behaves like Header's nav links: scroll on landing,
// route+scroll on other pages. Kept local since Footer is the only other
// consumer.
const SectionLink = ({ hash, children, className, testid }) => {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const onLanding = pathname === "/";
  const onClick = (e) => {
    if (onLanding) {
      e.preventDefault();
      const el = document.getElementById(hash);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    e.preventDefault();
    navigate({ pathname: "/", hash: `#${hash}` });
  };
  return (
    <a href={`/#${hash}`} onClick={onClick} className={className} data-testid={testid}>
      {children}
    </a>
  );
};

const Footer = () => {
  const { lang, t } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;
  const branding = useBranding();

  return (
    <footer className="bg-[#061b3a] text-white pt-16 pb-8">
      <div className="max-w-7xl mx-auto px-5 lg:px-8 grid md:grid-cols-4 gap-10">
        <div className="md:col-span-2">
          <SectionLink hash="home" className="inline-flex items-center gap-3" testid="footer-logo-link">
            {branding.logo_light ? (
              <img
                src={branding.logo_light}
                alt="PT. Intercloud Digital Inovasi"
                className="h-12 w-auto object-contain"
                style={branding.logo_light_source === "inverted" ? { filter: "brightness(0) invert(1)" } : undefined}
                loading="lazy"
                data-testid="footer-logo-img"
              />
            ) : (
              <span className="text-white font-extrabold tracking-tight" data-testid="footer-logo-fallback">INTERCLOUD</span>
            )}
          </SectionLink>
          <p className="mt-5 text-white/70 text-sm leading-relaxed max-w-md">
            {t("footer.tagline")}
          </p>
          <div className="mt-5 flex items-start gap-3 text-white/75 text-sm">
            <MapPin className="h-5 w-5 text-[#f5b120] flex-shrink-0 mt-0.5" />
            <span>{pick(ADDRESS, lang)}</span>
          </div>

          <div className="mt-5 flex items-center gap-3">
            <a href="https://www.instagram.com/intercloud.id/" target="_blank" rel="noreferrer" className="h-10 w-10 rounded-full bg-white/10 hover:bg-[#f5b120] hover:text-[#0a2350] flex items-center justify-center transition-colors">
              <Instagram className="h-4 w-4" />
            </a>
            <a href={waLink} target="_blank" rel="noreferrer" className="h-10 w-10 rounded-full bg-white/10 hover:bg-[#f5b120] hover:text-[#0a2350] flex items-center justify-center transition-colors">
              <MessageCircle className="h-4 w-4" />
            </a>
            <a href={`mailto:${EMAIL}`} className="h-10 w-10 rounded-full bg-white/10 hover:bg-[#f5b120] hover:text-[#0a2350] flex items-center justify-center transition-colors">
              <Mail className="h-4 w-4" />
            </a>
          </div>
        </div>

        <div>
          <h4 className="text-white font-bold mb-4">{t("footer.pages")}</h4>
          <ul className="space-y-2 text-sm text-white/70">
            <li><SectionLink hash="home" className="hover:text-[#f5b120]">{t("nav.home")}</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">{t("nav.services")}</SectionLink></li>
            <li><SectionLink hash="pop" className="hover:text-[#f5b120]">PoP</SectionLink></li>
            <li><SectionLink hash="pricing" className="hover:text-[#f5b120]">{t("nav.pricing")}</SectionLink></li>
            <li><SectionLink hash="faq" className="hover:text-[#f5b120]">{t("nav.faq")}</SectionLink></li>
            <li><SectionLink hash="contact" className="hover:text-[#f5b120]">{t("nav.contact")}</SectionLink></li>
            <li><Link to="/portal/login" className="hover:text-[#f5b120] font-semibold">{lang === "en" ? "Client Portal" : "Portal Klien"}</Link></li>
          </ul>
        </div>
        <div>
          <h4 className="text-white font-bold mb-4">{t("footer.services")}</h4>
          <ul className="space-y-2 text-sm text-white/70">
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">Cloud Service</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">VPS &amp; Hosting</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">Dedicated Server</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">Colocation</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">DC Interconnect</SectionLink></li>
            <li><SectionLink hash="services" className="hover:text-[#f5b120]">Firewall Solution</SectionLink></li>
          </ul>
          <h4 className="text-white font-bold mt-6 mb-3">Legal</h4>
          <ul className="space-y-2 text-sm text-white/70">
            <li><Link to="/legal/terms" className="hover:text-[#f5b120]">Terms of Service</Link></li>
            <li><Link to="/legal/aup" className="hover:text-[#f5b120]">Acceptable Use Policy</Link></li>
            <li><Link to="/legal/sla" className="hover:text-[#f5b120]">Service Level Agreement</Link></li>
          </ul>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-5 lg:px-8 mt-14 pt-6 border-t border-white/10 flex flex-col md:flex-row items-center justify-between gap-3">
        <div className="text-white/60 text-xs">
          © {new Date().getFullYear()} {t("footer.copy")}
        </div>
        <div className="text-white/60 text-xs">{t("footer.made")}</div>
      </div>
    </footer>
  );
};

export default Footer;
