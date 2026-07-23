import React, { lazy, Suspense } from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "./components/ui/toaster";
import { LanguageProvider } from "./i18n/LanguageContext";
import { AuthProvider } from "./portal/AuthContext";
import { RequireAuth } from "./portal/ProtectedRoute";
import ScrollToTop from "./components/ScrollToTop";

// Landing is LCP-critical for SEO — keep eager
import Landing from "./pages/Landing";

// ---- Lazy chunks --------------------------------------------------
// Legal
const TermsOfService        = lazy(() => import("./pages/LegalPages").then(m => ({ default: m.TermsOfService })));
const AcceptableUsePolicy   = lazy(() => import("./pages/LegalPages").then(m => ({ default: m.AcceptableUsePolicy })));
const ServiceLevelAgreement = lazy(() => import("./pages/LegalPages").then(m => ({ default: m.ServiceLevelAgreement })));

// Articles (public)
const ArticlesList  = lazy(() => import("./pages/ArticlesList"));
const ArticleDetail = lazy(() => import("./pages/ArticleDetail"));

// Portal shell + auth
const PortalLogin           = lazy(() => import("./pages/portal/PortalLogin"));
const PortalRegister        = lazy(() => import("./pages/portal/PortalRegister"));
const PortalForgotPassword  = lazy(() => import("./pages/portal/PortalForgotPassword"));
const PortalResetPassword   = lazy(() => import("./pages/portal/PortalResetPassword"));
const ChangePassword        = lazy(() => import("./pages/portal/ChangePassword"));
const PortalLayout          = lazy(() => import("./pages/portal/PortalLayout"));

// Client
const ClientDashboard = lazy(() => import("./pages/portal/client/ClientDashboard"));
const ClientServices  = lazy(() => import("./pages/portal/client/ClientServices"));
const ClientInvoices  = lazy(() => import("./pages/portal/client/ClientInvoices"));
const ClientTickets   = lazy(() => import("./pages/portal/client/ClientTickets"));
const ClientOrder     = lazy(() => import("./pages/portal/client/ClientOrder"));
const ClientTraffic   = lazy(() => import("./pages/portal/client/ClientTraffic"));

// Admin
const AdminDashboard    = lazy(() => import("./pages/portal/admin/AdminDashboard"));
const AdminUsers        = lazy(() => import("./pages/portal/admin/AdminUsers"));
const AdminProducts     = lazy(() => import("./pages/portal/admin/AdminProducts"));
const AdminOrders       = lazy(() => import("./pages/portal/admin/AdminOrders"));
const AdminInvoices     = lazy(() => import("./pages/portal/admin/AdminInvoices"));
const AdminQuotations   = lazy(() => import("./pages/portal/admin/AdminQuotations"));
const AdminTickets      = lazy(() => import("./pages/portal/admin/AdminTickets"));
const AdminFinance      = lazy(() => import("./pages/portal/admin/AdminFinance"));
const AdminIntegrations = lazy(() => import("./pages/portal/admin/AdminIntegrations"));
const AdminSecurity     = lazy(() => import("./pages/portal/admin/AdminSecurity"));
const AdminBranding     = lazy(() => import("./pages/portal/admin/AdminBranding"));
const AdminMail         = lazy(() => import("./pages/portal/admin/AdminMail"));
const AdminServices     = lazy(() => import("./pages/portal/admin/AdminServices"));
const AdminAssets       = lazy(() => import("./pages/portal/admin/AdminAssets"));
const AdminMikrotik     = lazy(() => import("./pages/portal/admin/AdminMikrotik"));
const AdminDiagnostics  = lazy(() => import("./pages/portal/admin/AdminDiagnostics"));
const AdminEmails       = lazy(() => import("./pages/portal/admin/AdminEmails"));
const AdminArticles     = lazy(() => import("./pages/portal/admin/AdminArticles"));
const AdminCategories   = lazy(() => import("./pages/portal/admin/AdminCategories"));

// Admin (mocked/business chunk)
const AdminSubscriptions = lazy(() => import("./pages/portal/admin/AdminMockedScreens").then(m => ({ default: m.AdminSubscriptions })));
const AdminProvisioning  = lazy(() => import("./pages/portal/admin/AdminMockedScreens").then(m => ({ default: m.AdminProvisioning })));
const AdminDCIM          = lazy(() => import("./pages/portal/admin/AdminMockedScreens").then(m => ({ default: m.AdminDCIM })));
const AdminCRM           = lazy(() => import("./pages/portal/admin/AdminBusiness").then(m => ({ default: m.AdminCRM })));
const AdminProjects      = lazy(() => import("./pages/portal/admin/AdminBusiness").then(m => ({ default: m.AdminProjects })));
const AdminContent       = lazy(() => import("./pages/portal/admin/AdminBusiness").then(m => ({ default: m.AdminContent })));
const AdminFollowups     = lazy(() => import("./pages/portal/admin/AdminBusiness").then(m => ({ default: m.AdminFollowups })));
const AdminDocuments     = lazy(() => import("./pages/portal/admin/AdminBusiness").then(m => ({ default: m.AdminDocuments })));

// ---- Route-loading fallback --------------------------------------
const RouteFallback = () => (
  <div className="min-h-screen flex items-center justify-center bg-white" data-testid="route-fallback">
    <div className="flex flex-col items-center gap-3">
      <div className="w-10 h-10 rounded-full border-2 border-[#0a2540] border-t-transparent animate-spin"></div>
      <div className="text-xs uppercase tracking-widest text-slate-500">Loading…</div>
    </div>
  </div>
);

function App() {
  return (
    <div className="App ic-font">
      <LanguageProvider>
        <BrowserRouter>
          <ScrollToTop />
          <AuthProvider>
            <Suspense fallback={<RouteFallback />}>
              <Routes>
                {/* Public marketing */}
                <Route path="/" element={<Landing />} />
                <Route path="/articles" element={<ArticlesList />} />
                <Route path="/articles/:slug" element={<ArticleDetail />} />
                <Route path="/legal/terms" element={<TermsOfService />} />
                <Route path="/legal/aup" element={<AcceptableUsePolicy />} />
                <Route path="/legal/sla" element={<ServiceLevelAgreement />} />

                {/* Portal */}
                <Route path="/portal/login" element={<PortalLogin />} />
                <Route path="/portal/register" element={<PortalRegister />} />
                <Route path="/portal/forgot-password" element={<PortalForgotPassword />} />
                <Route path="/portal/reset-password" element={<PortalResetPassword />} />

                <Route
                  path="/portal/client"
                  element={<RequireAuth role="client"><PortalLayout variant="client" /></RequireAuth>}
                >
                  <Route index element={<Navigate to="dashboard" replace />} />
                  <Route path="dashboard" element={<ClientDashboard />} />
                  <Route path="services" element={<ClientServices />} />
                  <Route path="invoices" element={<ClientInvoices />} />
                  <Route path="tickets" element={<ClientTickets />} />
                  <Route path="order" element={<ClientOrder />} />
                  <Route path="traffic" element={<ClientTraffic />} />
                  <Route path="settings/password" element={<ChangePassword />} />
                </Route>

                <Route
                  path="/portal/admin"
                  element={<RequireAuth role="staff"><PortalLayout variant="admin" /></RequireAuth>}
                >
                  <Route index element={<Navigate to="dashboard" replace />} />
                  <Route path="dashboard" element={<AdminDashboard />} />
                  <Route path="users" element={<AdminUsers />} />
                  <Route path="products" element={<AdminProducts />} />
                  <Route path="services" element={<AdminServices />} />
                  <Route path="addons" element={<AdminProducts />} />
                  <Route path="categories" element={<AdminCategories />} />
                  <Route path="orders" element={<AdminOrders />} />
                  <Route path="invoices" element={<AdminInvoices />} />
                  <Route path="quotations" element={<AdminQuotations />} />
                  <Route path="tickets" element={<AdminTickets />} />
                  <Route path="finance" element={<AdminFinance />} />
                  <Route path="assets" element={<AdminAssets />} />
                  <Route path="mail" element={<AdminMail />} />
                  <Route path="email" element={<AdminEmails />} />
                  <Route path="articles" element={<AdminArticles />} />
                  <Route path="provisioning" element={<AdminProvisioning />} />
                  <Route path="mikrotik" element={<AdminMikrotik />} />
                  <Route path="dcim" element={<AdminDCIM />} />
                  <Route path="diagnostics" element={<AdminDiagnostics />} />
                  <Route path="crm" element={<AdminCRM />} />
                  <Route path="projects" element={<AdminProjects />} />
                  <Route path="content" element={<AdminContent />} />
                  <Route path="followups" element={<AdminFollowups />} />
                  <Route path="documents" element={<AdminDocuments />} />
                  <Route path="integrations" element={<AdminIntegrations />} />
                  <Route path="security" element={<AdminSecurity />} />
                  <Route path="branding" element={<AdminBranding />} />
                  <Route path="real-integrations" element={<Navigate to="/portal/admin/integrations" replace />} />
                  <Route path="settings/password" element={<ChangePassword />} />
                </Route>

                <Route path="/portal" element={<Navigate to="/portal/login" replace />} />
              </Routes>
            </Suspense>
          </AuthProvider>
        </BrowserRouter>
        <Toaster />
      </LanguageProvider>
    </div>
  );
}

export default App;
