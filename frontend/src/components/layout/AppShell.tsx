import { Suspense, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Bell,
  Building2,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  CreditCard,
  HandCoins,
  LayoutDashboard,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ReceiptText,
  Search,
  Settings2,
  ScrollText,
  Sparkles,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { useApi } from "../../hooks/useApi";
import { cn, initials, timeAgo } from "../../lib/utils";
import { NAV_GROUPS, pageForPath } from "../../lib/navigation";
import type { Approval } from "../../lib/types";
import { Badge, PageSkeleton } from "../ui";
import { BrandLogo, BrandMark } from "../BrandLogo";
import { CommandPalette } from "../command/CommandPalette";
import { CopilotLauncher, CopilotPanel } from "../copilot/CopilotPanel";
import { ThemeMenuRow, ThemeToggle } from "./ThemeToggle";

const SIDEBAR_KEY = "finovexa_sidebar_collapsed";

interface PendingResponse {
  items: Approval[];
  pending_count: number;
}

const BOTTOM_LINKS = [
  { to: "/", label: "Home", icon: LayoutDashboard, end: true },
  { to: "/billing", label: "Billing", icon: ReceiptText },
  { to: "/recovery", label: "Recovery", icon: HandCoins },
  { to: "/payments", label: "Payments", icon: CreditCard },
];

function Sidebar({
  collapsed,
  pendingCount,
  onToggle,
  onNavigate,
  showToggle = true,
}: {
  collapsed: boolean;
  pendingCount: number;
  onToggle?: () => void;
  onNavigate?: () => void;
  showToggle?: boolean;
}) {
  const { user, profile, demoMode } = useAuth();
  const businessInitials = initials(profile?.business_name || "FINOVEXA");

  return (
    <div className="relative flex h-full flex-col overflow-hidden border-r border-white/[0.06] bg-[linear-gradient(180deg,#071120_0%,#0a1628_48%,#060e1b_100%)] text-slate-300">
      <div
        className="pointer-events-none absolute -left-24 top-0 h-64 w-64 rounded-full bg-brand-500/20 blur-3xl"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -right-16 bottom-10 h-52 w-52 rounded-full bg-cyan-400/10 blur-3xl"
        aria-hidden
      />

      <div
        className={cn(
          "relative flex h-16 shrink-0 items-center gap-2 px-4",
          collapsed ? "justify-center px-2" : "justify-between",
        )}
      >
        {collapsed ? <BrandMark className="h-9 w-9" /> : <BrandLogo subtitle="Business operations" />}
        {!collapsed && showToggle && onToggle && (
          <button
            type="button"
            onClick={onToggle}
            className="rounded-lg p-1.5 text-slate-500 transition hover:bg-white/[0.06] hover:text-slate-200"
            aria-label="Collapse sidebar"
            title="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      {collapsed ? (
        <Link
          to="/settings"
          onClick={onNavigate}
          title={profile?.business_name || "Workspace settings"}
          className="relative mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] text-[11px] font-bold text-slate-200 transition hover:border-white/20"
        >
          {businessInitials}
        </Link>
      ) : (
        <Link
          to="/settings"
          onClick={onNavigate}
          className="relative mx-3 mb-3 rounded-xl border border-white/[0.07] bg-white/[0.04] px-3 py-2.5 transition hover:border-white/[0.14] hover:bg-white/[0.06]"
        >
          <div className="flex items-center gap-2">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-white/[0.07] text-[10px] font-bold text-slate-200">
              {businessInitials}
            </span>
            <p className="min-w-0 flex-1 truncate text-xs font-semibold text-slate-200">
              {profile?.business_name || "Your workspace"}
            </p>
            {demoMode && <Badge tone="navy">DEMO</Badge>}
          </div>
          <p className="mt-1 pl-8 text-[10px] text-slate-500">
            {profile?.currency || "INR"} · {profile?.timezone || "Asia/Kolkata"}
          </p>
        </Link>
      )}

      <nav
        className={cn("relative flex-1 overflow-y-auto overflow-x-hidden pb-3", collapsed ? "px-2" : "px-3")}
        aria-label="Main navigation"
      >
        {NAV_GROUPS.map((group, groupIndex) => (
          <div key={group.label} className={collapsed ? "mb-1" : "mb-4"}>
            {collapsed ? (
              groupIndex > 0 && <div className="mx-2 my-2 border-t border-white/[0.06]" aria-hidden />
            ) : (
              <p className="px-3 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-600">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const showPending = item.to === "/approvals" && pendingCount > 0;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    title={collapsed ? item.label : item.hint}
                    className={({ isActive }) =>
                      cn(
                        "sidebar-link group",
                        collapsed && "justify-center px-0",
                        isActive && "sidebar-link-active",
                      )
                    }
                  >
                    <span className="relative shrink-0">
                      <item.icon className="h-[15px] w-[15px] opacity-85" aria-hidden />
                      {showPending && collapsed && (
                        <span className="absolute -right-1 -top-1 h-1.5 w-1.5 rounded-full bg-brand-400 ring-2 ring-navy-950" />
                      )}
                    </span>
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {!collapsed && showPending && (
                      <span className="ml-auto rounded-full bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-brand-200 ring-1 ring-brand-400/30">
                        {pendingCount}
                      </span>
                    )}
                    {!collapsed && !showPending && (
                      <ChevronRight
                        className="ml-auto h-3 w-3 shrink-0 opacity-0 transition group-hover:opacity-40"
                        aria-hidden
                      />
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className={cn("relative border-t border-white/[0.06] p-3", collapsed && "px-2")}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <span
              className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[10px] font-bold text-white"
              title={user?.full_name || "FINOVEXA user"}
            >
              {initials(user?.full_name || "FINOVEXA User")}
            </span>
            {onToggle && showToggle && (
              <button
                type="button"
                onClick={onToggle}
                className="rounded-lg p-1.5 text-slate-500 transition hover:bg-white/[0.06] hover:text-slate-200"
                aria-label="Expand sidebar"
                title="Expand sidebar"
              >
                <PanelLeftOpen className="h-4 w-4" />
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-violet-500 text-[11px] font-bold text-white">
                  {initials(user?.full_name || "FINOVEXA User")}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-slate-200">{user?.full_name}</p>
                  <p className="truncate text-[10px] text-slate-500">{user?.email}</p>
                </div>
              </div>
              <p className="mt-2.5 flex items-center gap-1.5 text-[10px] leading-relaxed text-slate-500">
                <ShieldCheck className="h-3 w-3 shrink-0 text-emerald-400/80" aria-hidden />
                Consequential actions need approval.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between px-1">
              <p className="text-[9px] tracking-wide text-slate-600">FINOVEXA AI · v1.0</p>
              {onToggle && showToggle && (
                <button
                  type="button"
                  onClick={onToggle}
                  className="rounded-md p-1 text-slate-600 transition hover:bg-white/[0.06] hover:text-slate-300"
                  aria-label="Collapse sidebar"
                  title="Collapse sidebar"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function AppShell() {
  const { user, profile, demoMode, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      return false;
    }
  });
  const location = useLocation();
  const navigate = useNavigate();
  const pending = useApi<PendingResponse>("/approvals?status=pending");
  const pendingItems = pending.data?.items || [];
  const pendingCount = pending.data?.pending_count ?? 0;
  const alertCount = pendingCount;
  const current = pageForPath(location.pathname);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    } catch {
      // A blocked storage write should not stop the layout change.
    }
  }, [collapsed]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    const openPalette = () => setPaletteOpen(true);
    const openCopilot = () => setCopilotOpen(true);
    window.addEventListener("finovexa:open-palette", openPalette);
    window.addEventListener("finovexa:open-copilot", openCopilot);
    return () => {
      window.removeEventListener("finovexa:open-palette", openPalette);
      window.removeEventListener("finovexa:open-copilot", openCopilot);
    };
  }, []);

  useEffect(() => {
    setMobileOpen(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [location.pathname]);

  useEffect(() => {
    const refresh = () => pending.reload();
    window.addEventListener("finovexa:approvals-changed", refresh);
    return () => window.removeEventListener("finovexa:approvals-changed", refresh);
  }, [pending.reload]);

  const signOut = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="min-h-screen">
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-30 hidden transition-[width] duration-300 ease-out lg:block",
          collapsed ? "w-[78px]" : "w-[264px]",
        )}
      >
        <Sidebar
          collapsed={collapsed}
          pendingCount={pendingCount}
          onToggle={() => setCollapsed((value) => !value)}
        />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-navy-950/60 backdrop-blur-[2px] animate-fade-in"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-[280px] animate-slide-in-right shadow-pop">
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-4 z-10 rounded-md p-1.5 text-slate-400 hover:bg-white/10 hover:text-white"
              aria-label="Close navigation"
            >
              <X className="h-4 w-4" />
            </button>
            <Sidebar
              collapsed={false}
              pendingCount={pendingCount}
              onNavigate={() => setMobileOpen(false)}
              showToggle={false}
            />
          </div>
        </div>
      )}

      <div
        className={cn(
          "transition-[padding] duration-300 ease-out",
          collapsed ? "lg:pl-[78px]" : "lg:pl-[264px]",
        )}
      >
        <header className="sticky top-0 z-20 border-b border-[color:var(--border)] bg-[var(--surface-glass)] backdrop-blur-xl">
          <div className="flex h-16 items-center gap-2 px-3 sm:gap-3 sm:px-6">
            <button
              type="button"
              className="rounded-lg border border-[color:var(--border)] p-2 text-[var(--text-3)] transition hover:text-[var(--text-1)] lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="h-4 w-4" />
            </button>

            <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1.5 text-xs md:flex">
              <span className="font-medium text-[var(--text-3)]">Workspace</span>
              <ChevronRight className="h-3 w-3 text-[var(--text-3)]/60" aria-hidden />
              <span className="text-[var(--text-3)]">{current?.group || "Command"}</span>
              <ChevronRight className="h-3 w-3 text-[var(--text-3)]/60" aria-hidden />
              <span className="truncate font-semibold text-[var(--text-1)]">
                {current?.label || "Overview"}
              </span>
            </nav>

            <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
              <button
                type="button"
                onClick={() => setPaletteOpen(true)}
                className="flex h-9 w-9 items-center justify-center gap-2 rounded-lg border border-[color:var(--border)] bg-[var(--surface)] text-[var(--text-3)] transition hover:border-[color:var(--border-strong)] hover:text-[var(--text-2)] sm:w-[220px] sm:justify-start sm:px-3 xl:w-[260px]"
                aria-label="Open command palette"
              >
                <Search className="h-3.5 w-3.5 shrink-0" aria-hidden />
                <span className="hidden flex-1 text-left text-xs sm:inline">Search or jump to…</span>
                <span className="kbd ml-auto hidden sm:inline">⌘K</span>
              </button>

              <ThemeToggle />

              <details className="group/notif relative">
                <summary
                  className="relative flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-lg border border-[color:var(--border)] bg-[var(--surface)] text-[var(--text-3)] transition hover:border-[color:var(--border-strong)] hover:text-[var(--text-1)] [&::-webkit-details-marker]:hidden"
                  aria-label={`Notifications${alertCount ? `, ${alertCount} awaiting attention` : ""}`}
                >
                  <Bell className="h-4 w-4" />
                  {alertCount > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-500 px-1 text-[9px] font-bold text-white ring-2 ring-[var(--surface)]">
                      {alertCount > 99 ? "99+" : alertCount}
                    </span>
                  )}
                </summary>
                <div className="absolute right-0 mt-2 w-[320px] overflow-hidden rounded-xl border border-[color:var(--border)] bg-[var(--surface)] shadow-pop">
                  <div className="flex items-center justify-between gap-2 border-b border-[color:var(--border)] px-4 py-3">
                    <p className="text-[13px] font-semibold text-[var(--text-1)]">Notifications</p>
                    <span className="flex items-center gap-1.5">
                      {pendingCount > 0 && <Badge tone="amber">{pendingCount} to decide</Badge>}
                      {alertCount === 0 && <Badge tone="slate">All clear</Badge>}
                    </span>
                  </div>
                  <div className="max-h-[300px] overflow-y-auto p-1.5">
                    {pendingItems.length === 0 ? (
                      <p className="px-3 py-6 text-center text-xs text-[var(--text-3)]">
                        No decisions are waiting.
                      </p>
                    ) : (
                      <>
                        {pendingItems.slice(0, 5).map((approval) => (
                            <button
                              key={`appr-${approval.id}`}
                              type="button"
                              onClick={() => navigate("/approvals")}
                              className="flex w-full items-start gap-2.5 rounded-lg px-3 py-2.5 text-left transition hover:bg-[var(--surface-2)]"
                            >
                              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
                                <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-xs font-semibold text-[var(--text-1)]">
                                  {approval.title}
                                </span>
                                <span className="mt-0.5 block truncate text-[10px] text-[var(--text-3)]">
                                  {approval.action_type} · {timeAgo(approval.created_at)}
                                </span>
                              </span>
                            </button>
                          ))}
                      </>
                    )}
                  </div>
                  <div className="border-t border-[color:var(--border)]">
                    <button
                      type="button"
                      onClick={() => navigate("/approvals")}
                      className="flex w-full items-center justify-center gap-1 px-2 py-2.5 text-[11px] font-semibold text-brand-600 transition hover:bg-[var(--surface-2)]"
                    >
                      Approval Center <ArrowRight className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              </details>

              <details className="relative hidden xl:block">
                <summary
                  className="flex h-9 cursor-pointer list-none items-center gap-2 rounded-lg border border-[color:var(--border)] bg-[var(--surface)] px-2.5 text-[var(--text-3)] transition hover:border-[color:var(--border-strong)] hover:text-[var(--text-1)] [&::-webkit-details-marker]:hidden"
                  aria-label="Workspace menu"
                >
                  <Building2 className="h-3.5 w-3.5" />
                  <span className="max-w-[130px] truncate text-[11px] font-semibold text-[var(--text-2)]">
                    {profile?.business_name || "Workspace"}
                  </span>
                  <ChevronRight className="h-3 w-3 rotate-90" aria-hidden />
                </summary>
                <div className="absolute right-0 mt-2 w-64 overflow-hidden rounded-xl border border-[color:var(--border)] bg-[var(--surface)] p-1.5 shadow-pop">
                  <div className="rounded-lg bg-[var(--surface-2)] px-3 py-2.5">
                    <p className="truncate text-xs font-semibold text-[var(--text-1)]">
                      {profile?.business_name || "Your workspace"}
                    </p>
                    <p className="mt-0.5 text-[10px] text-[var(--text-3)]">
                      {profile?.currency || "INR"} · {profile?.timezone || "Asia/Kolkata"}
                      {demoMode ? " · demo data" : ""}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate("/settings")}
                    className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <Settings2 className="h-3.5 w-3.5" /> Workspace settings
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate("/team")}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <Users className="h-3.5 w-3.5" /> Team access
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate("/payments")}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <CreditCard className="h-3.5 w-3.5" /> Payment center
                  </button>
                </div>
              </details>

              <details className="relative">
                <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg p-1 pr-1.5 transition hover:bg-[var(--surface-2)] [&::-webkit-details-marker]:hidden">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-violet-500 text-[11px] font-bold text-white">
                    {initials(user?.full_name || "FINOVEXA User")}
                  </span>
                  <span className="hidden leading-tight lg:block">
                    <span className="block max-w-[120px] truncate text-xs font-semibold text-[var(--text-1)]">
                      {user?.full_name}
                    </span>
                    <span className="block max-w-[120px] truncate text-[10px] text-[var(--text-3)]">
                      {user?.role ? user.role.replace(/^./, (c) => c.toUpperCase()) : profile?.business_name}
                    </span>
                  </span>
                  <ChevronRight className="hidden h-3 w-3 rotate-90 text-[var(--text-3)] lg:block" aria-hidden />
                </summary>
                <div className="absolute right-0 mt-2 w-56 overflow-hidden rounded-xl border border-[color:var(--border)] bg-[var(--surface)] p-1.5 shadow-pop">
                  <div className="px-3 py-2">
                    <p className="truncate text-xs font-semibold text-[var(--text-1)]">{user?.email}</p>
                    <p className="text-[10px] text-[var(--text-3)]">
                      {user?.role === "owner" ? "Owner workspace" : user?.role}
                    </p>
                  </div>
                  <ThemeMenuRow />
                  <div className="my-1 border-t border-[color:var(--border)]" />
                  <button
                    type="button"
                    onClick={() => navigate("/settings")}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <Settings2 className="h-3.5 w-3.5" /> Profile &amp; settings
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate("/audit")}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <ScrollText className="h-3.5 w-3.5" /> Activity log
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate("/ask")}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-2)] hover:bg-[var(--surface-2)]"
                  >
                    <Sparkles className="h-3.5 w-3.5" /> Ask FINOVEXA
                  </button>
                  <div className="my-1 border-t border-[color:var(--border)]" />
                  <button
                    type="button"
                    onClick={() => void signOut()}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-rose-600 hover:bg-rose-50"
                  >
                    <LogOut className="h-3.5 w-3.5" /> Sign out
                  </button>
                </div>
              </details>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1440px] px-4 pb-24 pt-6 sm:px-6 lg:px-8 lg:pb-8">
          <div key={location.pathname} className="page-enter">
            <Suspense fallback={<PageSkeleton cards={4} />}>
              <Outlet />
            </Suspense>
          </div>
          <footer className="mt-10 hidden flex-wrap items-center justify-between gap-2 border-t border-[color:var(--border)] pt-4 text-[10px] text-[var(--text-3)] lg:flex">
            <span>
              FINOVEXA AI · Every figure is traceable to the business ledger or labelled as an estimate.
            </span>
            <span className="flex items-center gap-1.5">
              <CircleHelp className="h-3 w-3" /> Orders require owner approval · Live only when enabled
            </span>
          </footer>
        </main>
      </div>

      <nav
        aria-label="Primary mobile navigation"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-[color:var(--border)] bg-[var(--surface-glass)] px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        <div className="flex items-stretch justify-around">
          {BOTTOM_LINKS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex flex-1 flex-col items-center gap-1 py-2 text-[10px] font-medium transition",
                  isActive ? "text-brand-600" : "text-[var(--text-3)]",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "flex h-7 w-10 items-center justify-center rounded-full transition",
                      isActive && "bg-brand-500/10",
                    )}
                  >
                    <item.icon className="h-[17px] w-[17px]" aria-hidden />
                  </span>
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="flex flex-1 flex-col items-center gap-1 py-2 text-[10px] font-medium text-[var(--text-3)]"
          >
            <span className="flex h-7 w-10 items-center justify-center rounded-full">
              <Menu className="h-[17px] w-[17px]" aria-hidden />
            </span>
            Menu
          </button>
        </div>
      </nav>

      <CopilotLauncher onClick={() => setCopilotOpen(true)} />
      <CopilotPanel open={copilotOpen} onClose={() => setCopilotOpen(false)} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onOpenCopilot={() => setCopilotOpen(true)}
      />
    </div>
  );
}

export function PageLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-700"
    >
      {children} <ArrowRight className="h-3 w-3" />
    </NavLink>
  );
}
