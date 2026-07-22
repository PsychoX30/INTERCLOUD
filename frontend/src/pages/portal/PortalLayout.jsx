import React, { useState } from "react";
import { NavLink, Outlet, Link } from "react-router-dom";
import {
  LayoutDashboard, ServerCog, Receipt, LifeBuoy, ShoppingCart, Activity,
  Users, Package, FileText, Wallet, Plug, HardDrive, Network, TerminalSquare,
  Send, Puzzle, Cloud, Menu, X, ChevronDown, LogOut, ExternalLink,
  UserSquare, ClipboardList, CalendarDays, CheckSquare, Files, FolderTree, Lock,
  Newspaper, ShieldCheck,
} from "lucide-react";
import { useAuth } from "../../portal/AuthContext";

const CLIENT_NAV = [
  { to: "/portal/client/dashboard", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard" },
  { to: "/portal/client/services", label: "My Services", icon: ServerCog, testid: "nav-services" },
  { to: "/portal/client/invoices", label: "Invoices", icon: Receipt, testid: "nav-invoices" },
  { to: "/portal/client/tickets", label: "Tickets", icon: LifeBuoy, testid: "nav-tickets" },
  { to: "/portal/client/order", label: "Order Service", icon: ShoppingCart, testid: "nav-order" },
  { to: "/portal/client/traffic", label: "Traffic Report", icon: Activity, testid: "nav-traffic" },
];

const ADMIN_NAV_GROUPS = [
  {
    label: "Overview",
    items: [{ key: "dashboard", to: "/portal/admin/dashboard", label: "Dashboard", icon: LayoutDashboard, testid: "nav-dashboard", roles: ["admin", "sales", "support", "ticket_only"] }],
  },
  {
    label: "Sales & Billing",
    items: [
      { key: "orders",     to: "/portal/admin/orders",     label: "Orders",     icon: ShoppingCart, testid: "nav-orders",     roles: ["admin", "sales"] },
      { key: "invoices",   to: "/portal/admin/invoices",   label: "Invoices",   icon: Receipt,      testid: "nav-invoices",   roles: ["admin"] },
      { key: "quotations", to: "/portal/admin/quotations", label: "Quotations", icon: FileText,     testid: "nav-quotations", roles: ["admin", "sales"] },
      { key: "finance",    to: "/portal/admin/finance",    label: "Finance",    icon: Wallet,       testid: "nav-finance",    roles: ["admin"] },
      { key: "assets",     to: "/portal/admin/assets",     label: "Assets",     icon: HardDrive,    testid: "nav-assets",     roles: ["admin"] },
    ],
  },
  {
    label: "Catalog",
    items: [
      { key: "products",   to: "/portal/admin/products",   label: "Products",   icon: Package,      testid: "nav-products",   roles: ["admin", "support"] },
      { key: "addons",     to: "/portal/admin/addons",     label: "Add-ons",    icon: Puzzle,       testid: "nav-addons",     roles: ["admin", "support"] },
      { key: "categories", to: "/portal/admin/categories", label: "Categories", icon: FolderTree,   testid: "nav-categories", roles: ["admin"] },
      { key: "services",   to: "/portal/admin/services",   label: "Services",   icon: ServerCog,    testid: "nav-services",   roles: ["admin", "sales", "support"] },
    ],
  },
  {
    label: "Support & CRM",
    items: [
      { key: "users",    to: "/portal/admin/users",    label: "Users / Clients", icon: Users,   testid: "nav-users",    roles: ["admin", "sales"] },
      { key: "tickets",  to: "/portal/admin/tickets",  label: "Tickets",         icon: LifeBuoy, testid: "nav-tickets",  roles: ["admin", "sales", "support", "ticket_only"] },
      { key: "mail",     to: "/portal/admin/mail",     label: "Webmail",         icon: Send,    testid: "nav-mail",     roles: ["admin", "sales", "support"] },
      { key: "email",    to: "/portal/admin/email",    label: "Email Automation", icon: Send,    testid: "nav-email",    roles: ["admin", "support"] },
      { key: "articles", to: "/portal/admin/articles", label: "Articles",         icon: Newspaper, testid: "nav-articles", roles: ["admin", "sales", "support"] },
    ],
  },
  {
    label: "Operations",
    items: [
      { key: "provisioning", to: "/portal/admin/provisioning", label: "Provisioning", icon: Cloud,          testid: "nav-provisioning", roles: ["admin", "support"] },
      { key: "mikrotik",     to: "/portal/admin/mikrotik",     label: "MikroTik Ops", icon: Network,        testid: "nav-mikrotik",     roles: ["admin", "support"] },
      { key: "dcim",         to: "/portal/admin/dcim",         label: "DCIM & IPAM",  icon: HardDrive,      testid: "nav-dcim",         roles: ["admin", "support"] },
      { key: "diagnostics",  to: "/portal/admin/diagnostics",  label: "Diagnostics",  icon: TerminalSquare, testid: "nav-diagnostics",  roles: ["admin", "sales", "support"] },
    ],
  },
  {
    label: "Business",
    items: [
      { key: "crm",       to: "/portal/admin/crm",       label: "Customer DB (CRM)", icon: UserSquare,    testid: "nav-crm",       roles: ["admin", "sales"] },
      { key: "projects",  to: "/portal/admin/projects",  label: "Project Tracker",   icon: ClipboardList, testid: "nav-projects",  roles: ["admin", "sales", "support"] },
      { key: "content",   to: "/portal/admin/content",   label: "Content Planner",   icon: CalendarDays,  testid: "nav-content",   roles: ["admin", "sales"] },
      { key: "followups", to: "/portal/admin/followups", label: "Follow-ups",        icon: CheckSquare,   testid: "nav-followups", roles: ["admin", "sales"] },
      { key: "documents", to: "/portal/admin/documents", label: "Documents",         icon: Files,         testid: "nav-documents", roles: ["admin", "sales", "support"] },
    ],
  },
  {
    label: "System",
    items: [
      { key: "integrations", to: "/portal/admin/integrations", label: "Integrations", icon: Plug, testid: "nav-integrations", roles: ["admin"] },
      { key: "security",     to: "/portal/admin/security",     label: "Security",     icon: ShieldCheck, testid: "nav-security", roles: ["admin"] },
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

  return (
    <div className="min-h-screen bg-slate-50 text-[#0a2350] ic-font flex">
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
          </div>
        </header>
        <main className="flex-1 p-4 md:p-8 min-w-0">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default PortalLayout;
