import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChartBar,
  Package,
  Tag,
  MapPin,
  FileText,
  Users,
  SignOut,
  Globe,
  UserCircle,
  List,
  X,
} from "@phosphor-icons/react";
import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function IcLogo() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid h-8 w-8 place-items-center rounded-md bg-[#0F172A] text-white">
        <span className="font-display text-[13px] font-bold tracking-tight">iC</span>
      </div>
      <div className="leading-tight">
        <div className="font-display text-[15px] font-bold tracking-tight text-slate-900">Intercloud</div>
        <div className="text-[10px] font-medium uppercase tracking-[0.2em] text-slate-500">Portal</div>
      </div>
    </div>
  );
}

const NAV = [
  { to: "/dashboard", labelKey: "common.dashboard", icon: ChartBar, testId: "nav-dashboard" },
  { to: "/assets", labelKey: "common.assets", icon: Package, testId: "nav-assets" },
  { to: "/categories", labelKey: "common.categories", icon: Tag, testId: "nav-categories" },
  { to: "/locations", labelKey: "common.locations", icon: MapPin, testId: "nav-locations" },
  { to: "/reports", labelKey: "common.reports", icon: FileText, testId: "nav-reports" },
  { to: "/users", labelKey: "common.users", icon: Users, adminOnly: true, testId: "nav-users" },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { t, lang, setLang } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const items = NAV.filter((n) => !n.adminOnly || user?.role === "admin");

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-screen bg-[#F8F9FA]">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-60 shrink-0 border-r border-slate-200 bg-white md:flex md:flex-col">
        <div className="border-b border-slate-200 px-5 py-5">
          <IcLogo />
        </div>
        <nav className="flex-1 space-y-1 px-2 py-4">
          {items.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              data-testid={n.testId}
              data-active={location.pathname.startsWith(n.to)}
              className={({ isActive }) =>
                `sidebar-link flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                  isActive
                    ? "bg-slate-100 text-slate-900"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`
              }
            >
              <n.icon size={18} weight="regular" />
              {t(n.labelKey)}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="grid h-8 w-8 place-items-center rounded-full bg-slate-100 text-slate-700">
              <UserCircle size={20} weight="regular" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-slate-900">{user?.name || "-"}</div>
              <div className="truncate text-[11px] uppercase tracking-wider text-slate-500">
                {user?.role || "-"}
              </div>
            </div>
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-slate-900/40"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <IcLogo />
              <button
                data-testid="mobile-close"
                onClick={() => setMobileOpen(false)}
                className="rounded-md p-1 text-slate-500 hover:bg-slate-100"
              >
                <X size={18} />
              </button>
            </div>
            <nav className="space-y-1 px-2 py-4">
              {items.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                      isActive ? "bg-slate-100 text-slate-900" : "text-slate-600"
                    }`
                  }
                >
                  <n.icon size={18} />
                  {t(n.labelKey)}
                </NavLink>
              ))}
            </nav>
          </div>
        </div>
      )}

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/95 px-4 backdrop-blur md:px-6">
          <button
            data-testid="mobile-open"
            className="rounded-md p-2 text-slate-600 hover:bg-slate-100 md:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <List size={20} />
          </button>
          <div className="font-display text-[15px] font-semibold tracking-tight text-slate-900">
            {t("auth.title")}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {/* Language toggle */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  data-testid="lang-toggle"
                  variant="ghost"
                  size="sm"
                  className="gap-2 rounded-full"
                >
                  <Globe size={16} />
                  <span className="text-xs font-semibold uppercase tracking-wider">{lang}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel>Language</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  data-testid="lang-id"
                  onClick={() => setLang("id")}
                >
                  Bahasa Indonesia
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="lang-en"
                  onClick={() => setLang("en")}
                >
                  English
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Profile */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  data-testid="profile-menu"
                  variant="ghost"
                  size="sm"
                  className="gap-2 rounded-full"
                >
                  <UserCircle size={18} />
                  <span className="hidden text-sm sm:inline">{user?.name || "-"}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuLabel className="truncate">{user?.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  data-testid="logout-button"
                  onClick={handleLogout}
                  className="text-red-600 focus:text-red-600"
                >
                  <SignOut size={16} className="mr-2" />
                  {t("common.logout")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 md:px-8 md:py-8" data-testid="main-content">
          <Outlet />
        </main>

        <footer className="border-t border-slate-200 px-4 py-4 text-[11px] uppercase tracking-[0.2em] text-slate-400 md:px-8">
          Intercloud Portal • Straight-Line Depreciation
        </footer>
      </div>
    </div>
  );
}
