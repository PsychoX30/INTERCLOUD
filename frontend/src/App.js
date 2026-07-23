import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Landing from "./pages/Landing";
import { Toaster } from "./components/ui/toaster";
import { LanguageProvider } from "./i18n/LanguageContext";
import { AuthProvider } from "./portal/AuthContext";
import { RequireAuth } from "./portal/ProtectedRoute";
import ScrollToTop from "./components/ScrollToTop";

// Legal
import { TermsOfService, AcceptableUsePolicy, ServiceLevelAgreement } from "./pages/LegalPages";

// Portal
import PortalLogin from "./pages/portal/PortalLogin";
import PortalRegister from "./pages/portal/PortalRegister";
import PortalForgotPassword from "./pages/portal/PortalForgotPassword";
import PortalResetPassword from "./pages/portal/PortalResetPassword";
import ChangePassword from "./pages/portal/ChangePassword";
import PortalLayout from "./pages/portal/PortalLayout";

// Client pages
import ClientDashboard from "./pages/portal/client/ClientDashboard";
import ClientServices from "./pages/portal/client/ClientServices";
import ClientInvoices from "./pages/portal/client/ClientInvoices";
import ClientTickets from "./pages/portal/client/ClientTickets";
import ClientOrder from "./pages/portal/client/ClientOrder";
import ClientTraffic from "./pages/portal/client/ClientTraffic";

// Admin pages
import AdminDashboard from "./pages/portal/admin/AdminDashboard";
import AdminUsers from "./pages/portal/admin/AdminUsers";
import AdminProducts from "./pages/portal/admin/AdminProducts";
import AdminOrders from "./pages/portal/admin/AdminOrders";
import AdminInvoices from "./pages/portal/admin/AdminInvoices";
import AdminQuotations from "./pages/portal/admin/AdminQuotations";
import AdminTickets from "./pages/portal/admin/AdminTickets";
import AdminFinance from "./pages/portal/admin/AdminFinance";
import AdminIntegrations from "./pages/portal/admin/AdminIntegrations";
import AdminSecurity from "./pages/portal/admin/AdminSecurity";
import AdminMail from "./pages/portal/admin/AdminMail";
import AdminServices from "./pages/portal/admin/AdminServices";
import AdminAssets from "./pages/portal/admin/AdminAssets";
import {
  AdminSubscriptions, AdminProvisioning, AdminDCIM,
} from "./pages/portal/admin/AdminMockedScreens";
import AdminMikrotik from "./pages/portal/admin/AdminMikrotik";
import AdminDiagnostics from "./pages/portal/admin/AdminDiagnostics";
import AdminEmails from "./pages/portal/admin/AdminEmails";
import AdminArticles from "./pages/portal/admin/AdminArticles";

// Public articles
import ArticlesList from "./pages/ArticlesList";
import ArticleDetail from "./pages/ArticleDetail";
import AdminCategories from "./pages/portal/admin/AdminCategories";
import {
  AdminCRM, AdminProjects, AdminContent, AdminFollowups, AdminDocuments,
} from "./pages/portal/admin/AdminBusiness";

function App() {
  return (
    <div className="App ic-font">
      <LanguageProvider>
        <BrowserRouter>
          <ScrollToTop />
          <AuthProvider>
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
                <Route path="real-integrations" element={<Navigate to="/portal/admin/integrations" replace />} />
                <Route path="settings/password" element={<ChangePassword />} />
              </Route>

              <Route path="/portal" element={<Navigate to="/portal/login" replace />} />
            </Routes>
          </AuthProvider>
        </BrowserRouter>
        <Toaster />
      </LanguageProvider>
    </div>
  );
}

export default App;
