import React from "react";
import { Helmet } from "react-helmet-async";

const ORIGIN = "https://intercloud-digital.com";
const TITLE = "PT. Intercloud Digital Inovasi | Layanan Cloud, Data Center & Solusi IT Indonesia";
const DESC = "PT. Intercloud Digital Inovasi menyediakan layanan Cloud, Hosting, VPS, Colocation, Dedicated Server, Lease to Own Appliance, Firewall Solution, dan DC to DC Connectivity terbaik di Indonesia dengan SLA 99,5% dan dukungan 24/7.";
const OG_DESC = "Penyedia layanan Cloud, Data Center, Konektivitas & Solusi IT terpercaya di Indonesia. SLA 99,5%, dukungan 24/7, harga terbaik.";
const OG_IMAGE = `${ORIGIN}/og-image.png`;

// Homepage/default SEO - mirrors the static tags in public/index.html that
// index.js strips at runtime so react-helmet-async is the single owner.
export const DefaultSeo = ({ title = TITLE, description = DESC, path = "/" }) => (
  <Helmet>
    <title>{title}</title>
    <meta name="description" content={description} />
    <link rel="canonical" href={`${ORIGIN}${path}`} />
    <meta property="og:type" content="website" />
    <meta property="og:url" content={`${ORIGIN}${path}`} />
    <meta property="og:title" content={title} />
    <meta property="og:description" content={OG_DESC} />
    <meta property="og:image" content={OG_IMAGE} />
    <meta property="og:locale" content="id_ID" />
    <meta property="og:site_name" content="PT. Intercloud Digital Inovasi" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content={title} />
    <meta name="twitter:description" content={OG_DESC} />
    <meta name="twitter:image" content={OG_IMAGE} />
  </Helmet>
);

export default DefaultSeo;
