import { useMemo } from "react";
import { useLang, useWaMessage } from "../i18n/LanguageContext";
import {
  WHATSAPP_PHONE,
  WHATSAPP_NUMBER,
  EMAIL,
  ADDRESS,
} from "../mock/data";

const DEFAULT_MAPS_URL =
  "https://maps.google.com/?q=Menara+Cakrawala+Jl+MH+Thamrin+No+9+Jakarta+Pusat";

const buildWaLink = (number, message) =>
  `https://wa.me/${number}?text=${encodeURIComponent(message)}`;

/**
 * Resolve the contact details the landing page renders.
 *
 * Admin ▸ Site Content ▸ Kontak writes `contact` on the landing-content
 * document, which has always round-tripped through the backend. This hook is
 * what makes those fields visible: each value falls back to the shipped
 * constant, so an untouched CMS renders exactly what the hardcoded strings did.
 *
 * The WhatsApp link is built from the *resolved* number, so changing the number
 * in the CMS moves the link too instead of leaving it pointing at the old one.
 */
export const useContact = () => {
  const { lang, contactOverride } = useLang();
  const waMessage = useWaMessage();

  // `contactOverride` is read inside the memo body, not captured from a
  // variable defined above it: `const o = contactOverride || {}` would mint a
  // fresh object on every render and make the memo pointless.
  return useMemo(() => {
    const o = contactOverride || {};
    const number = o.whatsapp_number || WHATSAPP_NUMBER;
    const phone = o.phone || WHATSAPP_PHONE;
    const email = o.email || EMAIL;
    const address = {
      id: o.address_id || ADDRESS.id,
      en: o.address_en || ADDRESS.en,
    };
    return {
      phone,
      number,
      email,
      address,
      addressText: address[lang] || address.id,
      mapsUrl: o.maps_url || DEFAULT_MAPS_URL,
      mailtoHref: `mailto:${email}`,
      // The generic key is what the shipped WHATSAPP_LINK_ID/_EN constant says,
      // so this link is unchanged until an admin edits the sentence or number.
      waLink: buildWaLink(number, waMessage("wa.prefilled.generic")),
      // Same number, caller-chosen message.
      waLinkWith: (message) => buildWaLink(number, message),
    };
  }, [contactOverride, lang, waMessage]);
};

export default useContact;
