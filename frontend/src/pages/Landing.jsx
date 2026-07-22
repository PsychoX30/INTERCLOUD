import React from "react";
import Header from "../components/Header";
import Hero from "../components/Hero";
import Features from "../components/Features";
import Infrastructure from "../components/Infrastructure";
import Services from "../components/Services";
import DecisionGuide from "../components/DecisionGuide";
import Pricing from "../components/Pricing";
import PoP from "../components/PoP";
import Partners from "../components/Partners";
import FAQ from "../components/FAQ";
import CTA from "../components/CTA";
import Footer from "../components/Footer";
import { MessageCircle } from "lucide-react";
import { WHATSAPP_LINK_ID, WHATSAPP_LINK_EN } from "../mock/data";
import { useLang } from "../i18n/LanguageContext";

const FloatingWA = () => {
  const { lang } = useLang();
  const waLink = lang === "en" ? WHATSAPP_LINK_EN : WHATSAPP_LINK_ID;
  return (
    <a
      href={waLink}
      target="_blank"
      rel="noreferrer"
      aria-label="Chat WhatsApp"
      data-testid="floating-whatsapp-btn"
      className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-[#25d366] text-white flex items-center justify-center shadow-xl hover:bg-[#20bd5a] transition-colors wa-pulse"
    >
      <MessageCircle className="h-6 w-6" />
    </a>
  );
};

const Landing = () => {
  return (
    <div className="bg-white text-[#0a2350]">
      <Header />
      <main>
        <Hero />
        <Features />
        <Infrastructure />
        <Services />
        <DecisionGuide />
        <Pricing />
        <PoP />
        <Partners />
        <FAQ />
        <CTA />
      </main>
      <Footer />
      <FloatingWA />
    </div>
  );
};

export default Landing;
