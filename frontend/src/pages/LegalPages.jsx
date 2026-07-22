import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Shield, FileText, Activity } from "lucide-react";
import Header from "../components/Header";
import Footer from "../components/Footer";
import { useLang } from "../i18n/LanguageContext";

const LEGAL_LINKS = [
  { to: "/legal/terms", label: "Terms of Service", icon: FileText },
  { to: "/legal/aup", label: "Acceptable Use Policy", icon: Shield },
  { to: "/legal/sla", label: "Service Level Agreement", icon: Activity },
];

export const LegalShell = ({ title, updated, kicker, children }) => {
  const { lang } = useLang();
  return (
    <div className="bg-slate-50 min-h-screen">
      <Header />
      <div className="pt-32 pb-20">
        <div className="max-w-4xl mx-auto px-5 lg:px-8">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-[#f5b120]">
            <ArrowLeft className="h-4 w-4" /> {lang === "en" ? "Back to home" : "Kembali ke beranda"}
          </Link>
          <div className="mt-6 mb-8">
            {kicker && (
              <div className="text-[#f5b120] text-xs font-bold tracking-[0.2em] uppercase mb-3">
                {kicker}
              </div>
            )}
            <h1 className="text-3xl md:text-5xl font-extrabold text-[#0a2350] leading-tight">
              {title}
            </h1>
            {updated && (
              <p className="mt-3 text-sm text-slate-500">Last updated: <b>{updated}</b></p>
            )}
          </div>

          {/* Cross-nav pills */}
          <div className="flex flex-wrap gap-2 mb-8 border-b border-slate-200 pb-4">
            {LEGAL_LINKS.map((l) => {
              const Icon = l.icon;
              return (
                <Link
                  key={l.to}
                  to={l.to}
                  className="inline-flex items-center gap-2 px-4 h-10 rounded-full bg-white border border-slate-200 hover:border-[#f5b120] hover:text-[#0a2350] text-sm text-slate-600 font-semibold transition-colors"
                >
                  <Icon className="h-3.5 w-3.5 text-[#f5b120]" /> {l.label}
                </Link>
              );
            })}
          </div>

          <article className="bg-white rounded-3xl shadow-sm border border-slate-200 p-8 md:p-12">
            <div className="legal-body text-slate-700 leading-relaxed">
              {children}
            </div>
          </article>

          <div className="mt-8 rounded-2xl bg-white border border-slate-200 p-5 flex flex-col md:flex-row md:items-center gap-4">
            <div className="text-sm text-slate-600">
              Questions about our policies? Our team is happy to walk you through anything.
            </div>
            <a
              href="https://wa.me/6287812397187?text=Halo%20Intercloud%2C%20saya%20ada%20pertanyaan%20tentang%20kebijakan%20layanan."
              target="_blank" rel="noreferrer"
              className="ml-auto inline-flex items-center gap-2 rounded-full bg-[#0a2350] hover:bg-[#f5b120] hover:text-[#0a2350] text-white px-5 py-2.5 text-sm font-semibold transition-colors"
            >
              Contact us via WhatsApp
            </a>
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
};

const H2 = ({ children }) => <h2 className="text-xl md:text-2xl font-extrabold text-[#0a2350] mt-10 first:mt-0 mb-3">{children}</h2>;
const P = ({ children }) => <p className="mb-4">{children}</p>;
const UL = ({ children }) => <ul className="list-disc pl-6 mb-5 space-y-1.5">{children}</ul>;
const Callout = ({ children }) => (
  <div className="my-6 rounded-2xl border-l-4 border-[#f5b120] bg-[#f5b120]/5 px-5 py-4 text-sm">
    {children}
  </div>
);

/* -------------------- Terms of Service -------------------- */
export const TermsOfService = () => (
  <LegalShell title="Terms of Service" updated="February 2026" kicker="Legal">
    <H2>1. Agreement</H2>
    <P>These Terms and Conditions govern the relationship between <b>PT Intercloud Digital Inovasi</b> ("Intercloud", "we", "us") and the customer ("you", "customer") for the use of our Cloud, Hosting, VPS, Colocation, Dedicated Server, Firewall, DC-to-DC Connectivity, and Lease-to-Own Appliance services. By placing an order, activating a service, or using our client portal, you accept these terms in full.</P>
    <P>Violating or ignoring any of the following terms will result in sanctions up to and including account suspension or termination — with or without prior notification depending on the severity.</P>

    <H2>2. Applicable Parties</H2>
    <P>This Agreement binds Intercloud and the customer whose identity is registered through our sales channels or client portal. Rights and obligations under this agreement cannot be transferred or assigned to any other party without our prior written consent.</P>

    <H2>3. Service Content & Usage</H2>
    <P>You agree to hold Intercloud harmless from any claim resulting from your use of our services. Intercloud is not responsible for the equipment, data, or content that a customer hosts on our infrastructure. All services must be used for legitimate purposes only.</P>
    <P>You are <b>PROHIBITED</b> from hosting or using our services for:</P>
    <UL>
      <li>Illegal hacking tools, phishing kits, malware, or pirated software</li>
      <li>Pornography, racism, hate speech, or content that promotes violence or terrorism</li>
      <li>Content that may cause social unrest, disputes, or intimidation</li>
      <li>Copyrighted material without authorization from the rightful owner</li>
      <li>Ponzi schemes, pyramid schemes, or any form of fraud</li>
      <li>Spam, DDoS attacks, port scanning, or network abuse</li>
      <li>Any activity that violates the laws and regulations of the Republic of Indonesia</li>
    </UL>

    <H2>4. Colocation & Infrastructure Usage</H2>
    <P>When using our Colocation, Dedicated Server, or Lease-to-Own services, you are prohibited from:</P>
    <UL>
      <li>Illegal gambling, hacking, carding, or crypto-mining without prior written approval</li>
      <li>Sending bulk email, spam, or unsolicited communications from our IP space</li>
      <li>Unauthorized port scanning, sniffing, or exploitation attempts</li>
      <li>Violating the acceptable use policies of our upstream providers or IXPs (APJII, OpenIXP, SGIX, etc.)</li>
      <li>Consuming resources in a way that impacts other customers on shared infrastructure</li>
    </UL>

    <H2>5. Resource Usage</H2>
    <P>Every service comes with allocated power, bandwidth, and network resources. If your usage exceeds the allocated capacity or disrupts other customers, Intercloud reserves the right to throttle, cap, or temporarily suspend the service until the issue is resolved. We will always attempt to notify you first, except in cases where immediate action is required to protect our network.</P>

    <H2>6. Billing & Payment</H2>
    <P>You agree to provide accurate contact and payment information during onboarding. Services are provisioned once payment confirmation is received — typically within 24 hours on working days.</P>
    <UL>
      <li>Invoices are issued based on the service activation date and are payable within the period stated on the invoice.</li>
      <li>Accounts unpaid within <b>7 days</b> after the due date are subject to service suspension.</li>
      <li>Accounts unpaid for more than <b>21 days</b> after suspension may be terminated and data permanently removed.</li>
      <li>Reactivation of terminated services may incur re-provisioning and setup fees.</li>
    </UL>
    <Callout>
      Accepted payment methods: <b>Bank transfer (Mandiri, BCA)</b> and <b>payment gateway (Duitku)</b> — details are displayed inside your invoice.
    </Callout>

    <H2>7. Refunds</H2>
    <P>You may request cancellation of a service at any time with reasonable notice. Refunds are subject to the following:</P>
    <UL>
      <li>Setup fees, hardware charges, and used service days are non-refundable.</li>
      <li>Refunds do not apply where service was suspended or terminated due to a Terms of Service violation.</li>
      <li>Approved refunds are processed within a maximum of <b>10 working days</b> after complete supporting documents are received.</li>
    </UL>

    <H2>8. Data Backup & Security</H2>
    <P>You use Intercloud services at your own risk. While we maintain redundant infrastructure and Tier III facilities, you remain responsible for backing up your own data. Intercloud is not liable for data loss resulting from system failures, security breaches on customer-managed equipment, or operator error. We strongly recommend that customers keep independent off-site backups of critical data.</P>

    <H2>9. Indemnification</H2>
    <P>You agree to defend, indemnify, and hold harmless Intercloud, its directors, employees, and affiliates from any and all claims, liabilities, losses, and reasonable attorney's fees arising from equipment, applications, or content hosted on our infrastructure — including but not limited to copyright infringement, illegal activity, or any harmful content that you or your users place on our network.</P>

    <H2>10. Disclaimer</H2>
    <P>Intercloud provides all services on an "as-is" basis, without any warranty (express or implied) of merchantability, fitness for a particular purpose, or non-infringement. We are not liable for any business damages arising from delays, outages, or circumstances beyond our reasonable control (force majeure).</P>

    <H2>11. Legal Compliance</H2>
    <P>Where required by Indonesian law or a valid court order, Intercloud may disclose customer information to law-enforcement authorities without prior notice. We cooperate with authorities to the extent required by the laws of the Republic of Indonesia.</P>

    <H2>12. Changes to These Terms</H2>
    <P>Intercloud reserves the right to modify these Terms of Service at any time. Continued use of our services after the changes become effective constitutes your acceptance of the modified terms. Disputes will be resolved amicably first (musyawarah), and failing that, in accordance with the applicable laws of the Republic of Indonesia.</P>

    <div className="mt-10 text-xs text-slate-500 border-t border-slate-100 pt-6">
      PT Intercloud Digital Inovasi · Menara Cakrawala 12th Fl, Unit 1205A, Jl. M.H. Thamrin No.9, Menteng, Central Jakarta 10340 · <a href="mailto:support@intercloud-digital.com" className="text-[#f5b120] font-semibold">support@intercloud-digital.com</a>
    </div>
  </LegalShell>
);

/* -------------------- Acceptable Use Policy -------------------- */
export const AcceptableUsePolicy = () => (
  <LegalShell title="Acceptable Use Policy" updated="February 2026" kicker="Legal">
    <H2>Overview</H2>
    <P>This Acceptable Use Policy ("AUP") governs the use of Intercloud's Cloud, Hosting, VPS, Colocation, Dedicated Server, Firewall, and Connectivity services. All customers must comply to keep a secure and reliable environment for everyone.</P>

    <H2>Prohibited Content</H2>
    <P>You may not host, distribute, or transmit content that is related to:</P>
    <UL>
      <li>Pornography, racism, hate speech, or content that promotes violence</li>
      <li>Illegal gambling or unlicensed gaming operations</li>
      <li>Content that could incite social unrest, disputes, or terror</li>
      <li>Copyrighted material without proper authorization</li>
      <li>Material intended to harass, threaten, or harm others</li>
      <li>Ponzi schemes, pyramid schemes, or any form of fraud</li>
      <li>Any material that violates the laws and regulations of Indonesia</li>
      <li>Content that our upstream providers or data-center facilities prohibit</li>
    </UL>

    <H2>Prohibited Network Activities</H2>
    <P>You may not use our services for:</P>
    <UL>
      <li>Sending bulk email, spam, or unsolicited commercial messages</li>
      <li>Operating IRC bots, PsyBNC, or similar IRC-related processes</li>
      <li>Running open web proxies, open mail relays, or unauthorized proxy services</li>
      <li>Unauthorized downloading, scraping, or file-transfer activity</li>
      <li>DDoS attacks, port scanning, sniffing, or system exploitation</li>
      <li>BitTorrent, peer-to-peer file sharing of infringing content</li>
      <li>Operating public-facing services without a registered domain</li>
      <li>Any activity prohibited by our upstream ISPs or the data centers we operate from</li>
    </UL>

    <H2>Email Usage Guidelines</H2>
    <UL>
      <li>Do not send spam or unsolicited bulk email</li>
      <li>Do not run mass email campaigns without proper authorization and opt-in lists</li>
      <li>Do not exceed <b>120 emails per hour, per account</b></li>
      <li>Do not send email containing any of the Prohibited Content above</li>
      <li>Do not use our IP space for any illegal or unauthorized purpose</li>
    </UL>
    <Callout>
      Cryptocurrency mining on our shared hosting and low-tier VPS plans is not allowed. Contact sales for dedicated GPU/CPU packages if you have a legitimate mining or ML workload.
    </Callout>

    <H2>Resource Usage</H2>
    <P>Use allocated resources (power, bandwidth, CPU, storage, IPs) responsibly. Excessive consumption that impacts other customers will be throttled or suspended. Intercloud monitors usage to ensure fair access for everyone.</P>

    <H2>Security Requirements</H2>
    <UL>
      <li>Maintain secure configurations on all customer-managed equipment</li>
      <li>Keep operating systems and applications updated with security patches</li>
      <li>Protect access credentials — do not share account passwords or API tokens</li>
      <li>Address reported security vulnerabilities promptly</li>
      <li>Notify Intercloud immediately of any security incident or breach affecting our network</li>
    </UL>

    <H2>Enforcement & Sanctions</H2>
    <P>Violations of this AUP may result in:</P>
    <UL>
      <li>A written warning by email for minor first-time violations</li>
      <li>Immediate suspension without prior notice for severe or repeated violations</li>
      <li>Termination of the service without refund for repeated or extreme violations</li>
      <li>Financial penalties where the violation caused measurable damage</li>
      <li>Legal action and reporting to law-enforcement authorities where warranted</li>
    </UL>

    <H2>Reporting Abuse</H2>
    <P>If you become aware of any activity that violates this Acceptable Use Policy from a service hosted on Intercloud infrastructure, please email <a href="mailto:abuse@intercloud-digital.com" className="text-[#f5b120] font-semibold">abuse@intercloud-digital.com</a> with full details (URLs, IP addresses, timestamps, headers). We investigate every report and take proportionate action.</P>

    <H2>Policy Updates</H2>
    <P>Intercloud reserves the right to modify this Acceptable Use Policy at any time. Significant changes will be communicated by email or via the client portal. Continued use of our services after a change takes effect constitutes acceptance of the updated policy.</P>
  </LegalShell>
);

/* -------------------- Service Level Agreement -------------------- */
export const ServiceLevelAgreement = () => (
  <LegalShell title="Service Level Agreement" updated="February 2026" kicker="Legal">
    <H2>Overview</H2>
    <P>This Service Level Agreement ("SLA") applies between <b>PT Intercloud Digital Inovasi</b> and each direct customer. It sets out the standards we commit to for the Cloud, Hosting, VPS, Colocation, Dedicated Server, Firewall, and DC-to-DC Connectivity services delivered from our Jakarta data-center points of presence.</P>

    <H2>1. Network Uptime Guarantee</H2>
    <P>We guarantee <b>99.5% network connectivity uptime per month</b>, excluding scheduled maintenance announced via our website or client portal. Our network features:</P>
    <UL>
      <li>Redundant upstream connectivity to multiple Tier-1 & Tier-2 providers</li>
      <li>Direct peering to major Indonesian Internet exchanges (APJII IIX, OpenIXP, SGIX)</li>
      <li>Multiple international transits for global reach</li>
      <li>24/7 network monitoring with automated alerting and human on-call response</li>
    </UL>
    <P>A network downtime claim can be filed if a continuous outage exceeds <b>0.5% of the month (approx. 3 hours 40 minutes)</b> and falls outside a scheduled maintenance window.</P>

    <H2>2. Power Uptime Guarantee</H2>
    <P>We guarantee <b>99.5% power uptime per month</b> for Colocation, Dedicated Server, and Lease-to-Own services. Our power stack includes:</P>
    <UL>
      <li>Redundant utility feeds with automatic transfer switches</li>
      <li>N+1 UPS systems for continuous power protection</li>
      <li>Backup generators with extended fuel capacity</li>
      <li>Regular preventive maintenance and load testing</li>
    </UL>

    <H2>3. Facility Access</H2>
    <UL>
      <li>24/7/365 physical access to your colocation space with proper identification</li>
      <li>Advance notice required (typically <b>2-4 hours</b>) for facility access</li>
      <li>Escort may be provided for security compliance</li>
      <li>Full access log maintained for audit purposes</li>
    </UL>

    <H2>4. Environmental Controls</H2>
    <P>Our data centers maintain the temperature, humidity, and airflow required by enterprise hardware — with precision cooling, humidity control, and continuous monitoring.</P>

    <H2>5. Physical Security</H2>
    <UL>
      <li>24/7 on-site manned security personnel</li>
      <li>Biometric access control at every perimeter layer</li>
      <li>CCTV with 90-day retention</li>
      <li>Multi-layer perimeter — building, floor, cage, rack</li>
    </UL>
    <P>Customers remain responsible for the security of their own equipment, data, and access credentials.</P>

    <H2>6. Technical Support & Remote Hands</H2>
    <P>Intercloud provides <b>24/7 technical support</b> covering:</P>
    <UL>
      <li>Remote-hands services for equipment power-cycling and cable checks</li>
      <li>Basic troubleshooting and diagnostic execution</li>
      <li>Network connectivity verification (BGP session, upstream ping)</li>
      <li>Facility and infrastructure support</li>
    </UL>
    <P>Response times vary by service tier and issue severity — critical infrastructure incidents receive the highest priority.</P>

    <H2>7. Scheduled Maintenance</H2>
    <P>We schedule preventive maintenance to keep the facility and network healthy. Customers receive <b>7-14 days advance notice</b> via email and the client portal for any planned maintenance that may impact services. We aim to schedule maintenance windows during off-peak hours (weekend nights) to minimize impact.</P>

    <H2>8. SLA Credits & Claims</H2>
    <P>If we fail to meet our uptime guarantees:</P>
    <UL>
      <li>Claims must be submitted within <b>7 days</b> of the incident via a support ticket</li>
      <li>Claims must include supporting documentation (timestamps, monitoring logs, tickets)</li>
      <li>Intercloud will verify the claim against our internal monitoring data</li>
      <li>Approved claims receive service credits or extended service terms</li>
      <li>SLA credits are not paid out as cash refunds</li>
    </UL>

    <H2>9. Exclusions</H2>
    <P>This SLA does not cover downtime caused by:</P>
    <UL>
      <li>Customer-managed equipment failures or misconfigurations</li>
      <li>Issues with the customer's own upstream ISP or last-mile provider</li>
      <li>Force majeure events (natural disasters, civil unrest, government orders)</li>
      <li>Scheduled maintenance announced with proper advance notice</li>
      <li>Violations of our Terms of Service or Acceptable Use Policy</li>
      <li>Downtime caused by customer action or negligence</li>
    </UL>

    <H2>10. Billing & Payment Terms</H2>
    <UL>
      <li>Invoices are issued <b>14 days before</b> the service renewal date</li>
      <li>Payment is due on the renewal date</li>
      <li>Late payments may result in service suspension after 7 days</li>
      <li>Services may be terminated after extended non-payment (see Terms of Service §6)</li>
      <li>Please confirm bank-transfer payments in the client portal or via WhatsApp to speed up reconciliation</li>
    </UL>

    <H2>11. Data & Backup Responsibility</H2>
    <P>Customers are solely responsible for backing up their own data. Intercloud maintains facility redundancy but does not guarantee against customer-side data loss and is not responsible for customer backups. Managed-backup add-ons are available — contact sales for pricing.</P>

    <H2>12. SLA Modifications</H2>
    <P>Intercloud reserves the right to modify this SLA with reasonable notice to customers. Significant changes will be communicated by email and via the client portal.</P>

    <div className="mt-10 text-xs text-slate-500 border-t border-slate-100 pt-6">
      PT Intercloud Digital Inovasi · Menara Cakrawala 12th Fl, Unit 1205A, Jl. M.H. Thamrin No.9, Menteng, Central Jakarta 10340 · <a href="mailto:noc@intercloud-digital.com" className="text-[#f5b120] font-semibold">noc@intercloud-digital.com</a>
    </div>
  </LegalShell>
);
