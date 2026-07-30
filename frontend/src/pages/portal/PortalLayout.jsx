import React, { useState, useEffect } from "react";
import { NavLink, Outlet, Link } from "react-router-dom";
import {
  LayoutDashboard, ServerCog, Receipt, LifeBuoy, ShoppingCart, Activity,
  Users, Package, FileText, Wallet, Plug, HardDrive, Network, TerminalSquare,
  Send, Puzzle, Cloud, Menu, X, ChevronDown, LogOut, ExternalLink,
  UserSquare, ClipboardList, CalendarDays, CheckSquare, Files, FolderTree, Lock,
  Newspaper, ShieldCheck, Image as ImageIcon, Layout, DatabaseBackup,
  History, MonitorCheck, ReceiptText, LineChart, Globe, Images, Link2, Globe2, FormInput,
  Bell, BookOpen,
} from "lucide-react";
import { useAuth } from "../../portal/AuthContext";
import { api } from "../../portal/api";

const CLIENT_NAV = [
  { to: "/portal/client/dashboard", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/portal/client/services", label: "My Services", icon: ServerCog, testid: "nav-services" },
  { to: "/portal/client/domains", label: "Domain", icon: Globe2, testid: "nav-domains" },
  { to: "/portal/client/invoices", label: "Invoices", icon: Receipt, testid: "nav-invoices" },
  { to: "/portal/client/credit-notes", label: "Credit Notes", icon: ReceiptText, testid: "nav-client-credit-notes" },
  { to: "/portal/client/tickets", label: "Tickets", icon: LifeBuoy, testid: "nav-tickets" },
  { to: "/portal/client/order", label: "Order Service", icon: ShoppingCart, testid: "nav-order" },
  { to: "/portal/client/traffic", label: "Traffic Report", icon: Activity, testid: "nav-traffic" },
  { to: "/portal/client/guide", label: "Panduan", icon: BookOpen, testid: "nav-guide" },
];

const ADMIN_NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { key: "dashboard", to: "/portal/admin/dashboard", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard", roles: ["admin", "sales", "finance", "support", "ticket_only", "creative"] },
      { key: "owner_dashboard", to: "/portal/admin/owner", label: "Executive Overview", icon: LineChart, testid: "nav-owner-dashboard", roles: ["admin", "owner"] },
    ],
  },
  {
    label: "Sales & Billing",
    items: [
      { key: "orders",     to: "/portal/admin/orders",     label: "Orders",     icon: ShoppingCart, testid: "nav-orders",     roles: ["admin", "sales", "finance"] },
      { key: "invoices",   to: "/portal/admin/invoices",   label: "Invoices",   icon: Receipt,      testid: "nav-invoices",   roles: ["admin", "finance"] },
      { key: "quotations", to: "/portal/admin/quotations", label: "Quotations", icon: FileText,     testid: "nav-quotations", roles: ["admin", "sales", "finance"] },
      { key: "finance",    to: "/portal/admin/finance",    label: "Finance",    icon: Wallet,       testid: "nav-finance",    roles: ["admin", "finance"] },
      { key: "assets",     to: "/portal/admin/assets",     label: "Assets",     icon: HardDrive,    testid: "nav-assets",     roles: ["admin", "finance"] },
      { key: "credit_notes", to: "/portal/admin/credit-notes", label: "Credit Notes", icon: ReceiptText, testid: "nav-credit-notes", roles: ["admin", "finance"] },
    ],
  },
  {
    label: "Catalog",
    items: [
      { key: "products",   to: "/portal/admin/products",   label: "Products",   icon: Package,      testid: "nav-products",   roles: ["admin", "support"] },
      { key: "addons",     to: "/portal/admin/addons",     label: "Add-ons",    icon: Puzzle,       testid: "nav-addons",     roles: ["admin", "support"] },
      { key: "categories", to: "/portal/admin/categories", label: "Categories", icon: FolderTree,   testid: "nav-categories", roles: ["admin"] },
      { key: "services",   to: "/portal/admin/services",   label: "Services",   icon: ServerCog,    testid: "nav-services",   roles: ["admin", "finance", "support"] },
    ],
  },
  {
    label: "Support & CRM",
    items: [
      { key: "users",    to: "/portal/admin/users",    label: "Users / Clients", icon: Users,   testid: "nav-users",    roles: ["admin", "sales", "finance", "support"] },
      { key: "tickets",  to: "/portal/admin/tickets",  label: "Tickets",         icon: LifeBuoy, testid: "nav-tickets",  roles: ["admin", "sales", "finance", "support", "ticket_only"] },
      { key: "mail",     to: "/portal/admin/mail",     label: "Webmail",         icon: Send,    testid: "nav-mail",     roles: ["admin", "sales", "finance", "support"] },
      { key: "email",    to: "/portal/admin/email",    label: "Email Automation", icon: Send,    testid: "nav-email",    roles: ["admin"] },
      { key: "articles", to: "/portal/admin/articles", label: "Articles",         icon: Newspaper, testid: "nav-articles", roles: ["admin", "sales", "finance", "support", "creative"] },
    ],
  },
  {
    label: "Operations",
    items: [
      { key: "provisioning", to: "/portal/admin/provisioning", label: "Provisioning", icon: Cloud,          testid: "nav-provisioning", roles: ["admin", "support"] },
      { key: "mikrotik",     to: "/portal/admin/mikrotik",     label: "MikroTik Ops", icon: Network,        testid: "nav-mikrotik",     roles: ["admin", "support"] },
      { key: "dcim",         to: "/portal/admin/dcim",         label: "DCIM & IPAM",  icon: HardDrive,      testid: "nav-dcim",         roles: ["admin", "support"] },
      { key: "diagnostics",  to: "/portal/admin/diagnostics",  label: "Diagnostics",  icon: TerminalSquare, testid: "nav-diagnostics",  roles: ["admin", "support"] },
      { key: "noc",          to: "/portal/admin/noc",          label: "NOC Monitor",  icon: MonitorCheck,   testid: "nav-noc",          roles: ["admin", "support"] },
    ],
  },
  {
    label: "Business",
    items: [
      { key: "crm",       to: "/portal/admin/crm",       label: "Customer DB (CRM)", icon: UserSquare,    testid: "nav-crm",       roles: ["admin", "sales", "finance", "support"] },
      { key: "projects",  to: "/portal/admin/projects",  label: "Project Tracker",   icon: ClipboardList, testid: "nav-projects",  roles: ["admin", "sales", "support"] },
      { key: "content",   to: "/portal/admin/content",   label: "Content Planner",   icon: CalendarDays,  testid: "nav-content",   roles: ["admin", "sales", "finance", "support", "creative"] },
      { key: "followups", to: "/portal/admin/followups", label: "Follow-ups",        icon: CheckSquare,   testid: "nav-followups", roles: ["admin", "sales", "finance", "support"] },
      { key: "documents", to: "/portal/admin/documents", label: "Documents",         icon: Files,         testid: "nav-documents", roles: ["admin", "sales", "finance", "support"] },
    ],
  },
  {
    label: "Creative",
    items: [
      { key: "media_library",    to: "/portal/admin/media-library",    label: "Media Library",    icon: Images,       testid: "nav-media-library",    roles: ["admin", "creative"] },
      { key: "content_calendar", to: "/portal/admin/content-calendar", label: "Content Calendar", icon: CalendarDays, testid: "nav-content-calendar", roles: ["admin", "creative"] },
      { key: "utm_builder",      to: "/portal/admin/utm-builder",      label: "UTM Builder",      icon: Link2,        testid: "nav-utm-builder",      roles: ["admin", "creative", "sales"] },
      { key: "form_builder",     to: "/portal/admin/form-builder",     label: "Form Builder",     icon: FormInput,    testid: "nav-form-builder",     roles: ["admin", "creative", "sales"] },
    ],
  },
  {
    label: "System",
    items: [
      { key: "integrations",  to: "/portal/admin/integrations",  label: "Integrations",   icon: Plug,           testid: "nav-integrations",  roles: ["admin"] },
      { key: "security",      to: "/portal/admin/security",      label: "Security",       icon: ShieldCheck,    testid: "nav-security",      roles: ["admin"] },
      { key: "audit_log",     to: "/portal/admin/audit-log",     label: "Audit Log",      icon: History,        testid: "nav-audit-log",     roles: ["admin"] },
      { key: "branding",      to: "/portal/admin/branding",      label: "Branding",       icon: ImageIcon,      testid: "nav-branding",      roles: ["admin"] },
      { key: "site_content",  to: "/portal/admin/site-content",  label: "Landing CMS",    icon: Layout,         testid: "nav-site-content",  roles: ["admin"] },
      { key: "backup",        to: "/portal/admin/backup",        label: "Backup & Restore", icon: DatabaseBackup, testid: "nav-backup",     roles: ["admin"] },
      { key: "status_page",   to: "/portal/admin/status-page",   label: "Public Status Page", icon: Globe,        testid: "nav-status-page",   roles: ["admin"] },
    ],
  },
];

const NavItem = ({ item, onClick }) => {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.to}
      onClick={onClick}
      data-testid={item.testid}
      className={({ isActive }) =>
        `group flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? "bg-[#f5b120] text-[#0a2350]"
            : "text-white/75 hover:bg-white/10 hover:text-white"
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={isActive ? 2.2 : 1.8} />
          <span className="truncate">{item.label}</span>
        </>
      )}
    </NavLink>
  );
};

const PortalLayout = ({ variant = "client" }) => {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const isAdmin = variant === "admin";
  const impersonating = typeof window !== "undefined" && localStorage.getItem("ic_admin_return");

  const returnToAdmin = () => {
    const t = localStorage.getItem("ic_admin_return");
    localStorage.removeItem("ic_admin_return");
    localStorage.removeItem("ic_impersonating");
    if (t) localStorage.setItem("ic_portal_token", t);
    window.location.href = "/portal/admin/users";
  };

  return (
    <div className="min-h-screen bg-slate-50 text-[#0a2350] ic-font flex flex-col">
      {impersonating && !isAdmin && (
        <div className="sticky top-0 z-[60] bg-indigo-700 text-white px-4 py-2 flex items-center justify-center gap-3 text-sm" data-testid="impersonation-banner">
          <span>Mode impersonasi: Anda melihat portal sebagai <b>{localStorage.getItem("ic_impersonating")}</b></span>
          <button onClick={returnToAdmin} className="bg-white text-indigo-700 font-bold text-xs rounded-full px-3 py-1 hover:bg-indigo-50" data-testid="impersonation-return-btn">
            Kembali ke Admin
          </button>
        </div>
      )}
      <div className="flex flex-1">
      {/* Sidebar */}
      <aside
        className={`fixed lg:sticky top-0 left-0 h-screen lg:self-start w-72 bg-[#0a2350] text-white z-50 transform transition-transform lg:transform-none ${
          open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        } flex flex-col flex-shrink-0`}
      >
        <div className="flex items-center justify-between px-5 py-5 border-b border-white/10">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-lg bg-[#f5b120] flex items-center justify-center">
              <Cloud className="h-5 w-5 text-[#0a2350]" strokeWidth={2} />
            </div>
            <div>
              <div className="text-xs font-bold tracking-widest text-[#f5b120]">INTERCLOUD</div>
              <div className="text-[13px] font-extrabold leading-tight">
                {isAdmin ? "Admin Console" : "Client Portal"}
              </div>
            </div>
          </Link>
          <button className="lg:hidden text-white/70" onClick={() => setOpen(false)}>
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto no-scrollbar px-3 py-4 space-y-1">
          {isAdmin ? (
            ADMIN_NAV_GROUPS.map((grp) => {
              const items = grp.items.filter((it) => {
                if (it.roles && !it.roles.includes(user?.role)) return false;
                // Fine-grained override: if user.menu_keys is set, restrict to that list.
                if (Array.isArray(user?.menu_keys) && user.menu_keys.length > 0) {
                  return user.menu_keys.includes(it.key);
                }
                return true;
              });
              if (items.length === 0) return null;
              return (
                <div key={grp.label} className="mt-4 first:mt-0">
                  <div className="px-3 text-[10px] uppercase tracking-widest text-white/40 font-bold mb-1.5">
                    {grp.label}
                  </div>
                  {items.map((it) => (
                    <NavItem key={it.to} item={it} onClick={() => setOpen(false)} />
                  ))}
                </div>
              );
            })
          ) : (
            CLIENT_NAV.map((it) => <NavItem key={it.to} item={it} onClick={() => setOpen(false)} />)
          )}
        </nav>

        <div className="px-3 py-3 border-t border-white/10">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-white/5">
            <div className="h-9 w-9 rounded-full bg-[#f5b120] text-[#0a2350] flex items-center justify-center font-extrabold text-sm">
              {(user?.name || "?").split(" ").map((w) => w[0]).slice(0, 2).join("")}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-bold truncate">{user?.name}</div>
              <div className="text-[11px] text-white/60 truncate">{user?.email}</div>
            </div>
            <NavLink
              to={isAdmin ? "/portal/admin/settings/password" : "/portal/client/settings/password"}
              onClick={() => setOpen(false)}
              data-testid="change-pw-link"
              className="h-8 w-8 rounded-lg hover:bg-white/10 flex items-center justify-center text-white/70 hover:text-[#f5b120] transition-colors"
              title="Change password"
            >
              <Lock className="h-4 w-4" />
            </NavLink>
            <button
              onClick={logout}
              data-testid="logout-btn"
              className="h-8 w-8 rounded-lg hover:bg-white/10 flex items-center justify-center text-white/70 hover:text-[#f5b120] transition-colors"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Backdrop for mobile */}
      {open && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="sticky top-0 z-30 bg-white border-b border-slate-200 h-14 flex items-center px-5 gap-4">
          <button className="lg:hidden text-slate-600" onClick={() => setOpen(true)}>
            <Menu className="h-5 w-5" />
          </button>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="hidden sm:inline">Signed in as</span>
            <span className="font-bold text-[#0a2350]">{user?.name}</span>
            <span className={`px-2 py-0.5 text-[10px] rounded-full font-bold uppercase tracking-wider ${
              isAdmin ? "bg-[#f5b120]/20 text-[#0a2350]" : "bg-emerald-100 text-emerald-700"
            }`}>{user?.role}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <Link
              to="/"
              className="text-xs text-slate-500 hover:text-[#f5b120] inline-flex items-center gap-1"
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink className="h-3.5 w-3.5" /> View website
            </Link>
            {user?.role !== "client" && <NotificationsBell />}
            <button
              onClick={logout}
              data-testid="mobile-logout-btn"
              title="Sign out"
              className="lg:hidden h-9 w-9 rounded-lg flex items-center justify-center text-slate-500 hover:text-red-600 hover:bg-slate-100 transition-colors"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 p-4 md:p-8 min-w-0">
          <Outlet />
        </main>
      </div>
      </div>
    </div>
  );
};

const SEVERITY_STYLES = {
  danger: "bg-red-50 border-red-200 text-red-700",
  warning: "bg-amber-50 border-amber-200 text-amber-800",
  info: "bg-blue-50 border-blue-200 text-blue-800",
};

const NotificationsBell = () => {
  const [alerts, setAlerts] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.get("/admin/notifications")
        .then((r) => {
          if (!alive) return;
          setAlerts(r.data?.alerts || []);
          setUnread(r.data?.unread ?? (r.data?.alerts || []).length);
        })
        .catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const markRead = async (keys) => {
    const ks = keys.filter(Boolean);
    if (!ks.length) return;
    setAlerts((prev) => prev.map((a) => (ks.includes(a.key) ? { ...a, read: true } : a)));
    setUnread((u) => Math.max(0, u - ks.length));
    try { await api.post("/admin/notifications/mark-read", { keys: ks }); } catch (e) { /* best-effort */ }
  };

  const unreadKeys = alerts.filter((a) => !a.read).map((a) => a.key);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        data-testid="admin-notif-bell"
        title="Notifikasi"
        className="relative h-9 w-9 rounded-lg flex items-center justify-center text-slate-500 hover:text-[#0a2350] hover:bg-slate-100 transition-colors"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span
            data-testid="admin-notif-count"
            className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-red-600 text-white text-[10px] font-bold flex items-center justify-center"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 mt-2 w-80 max-h-96 overflow-y-auto bg-white rounded-xl shadow-2xl border border-slate-200 z-50 p-2"
            data-testid="admin-notif-dropdown"
          >
            <div className="px-2 py-1.5 flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-widest text-slate-500">
                Notifikasi ({unread} baru)
              </span>
              {unreadKeys.length > 0 && (
                <button
                  onClick={() => markRead(unreadKeys)}
                  className="text-[11px] font-bold text-[#0a2350] hover:text-[#f5b120]"
                  data-testid="admin-notif-mark-all"
                >
                  Tandai semua dibaca
                </button>
              )}
            </div>
            {alerts.length === 0 ? (
              <div className="px-2 py-4 text-sm text-slate-500 text-center">Tidak ada notifikasi.</div>
            ) : (
              alerts.map((a, i) => (
                <Link
                  key={a.key || i}
                  to={a.link || "#"}
                  onClick={() => { if (!a.read) markRead([a.key]); setOpen(false); }}
                  className={`block rounded-lg border px-3 py-2 mb-1.5 text-xs hover:opacity-80 transition-opacity ${
                    a.read
                      ? "bg-white border-slate-200 text-slate-500"
                      : SEVERITY_STYLES[a.severity] || SEVERITY_STYLES.info
                  }`}
                  data-testid={`admin-notif-item-${a.type}`}
                >
                  <div className="font-bold flex items-center gap-1.5">
                    {!a.read && <span className="h-1.5 w-1.5 rounded-full bg-current shrink-0" data-testid="admin-notif-unread-dot" />}
                    {a.title}
                  </div>
                  <div className="mt-0.5 opacity-80">{a.detail}</div>
                </Link>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default PortalLayout;
