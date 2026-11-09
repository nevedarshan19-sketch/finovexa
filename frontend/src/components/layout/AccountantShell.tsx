import { Suspense } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BadgeCheck,
  Building2,
  ClipboardList,
  Database,
  FileSearch,
  FileSpreadsheet,
  FileStack,
  FileText,
  FlaskConical,
  Inbox,
  LayoutDashboard,
  LogOut,
  ReceiptIndianRupee,
  ShieldCheck,
  ScrollText,
  UsersRound,
  Wallet,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cn, initials } from "../../lib/utils";
import { Badge, PageSkeleton } from "../ui";

const SENIOR_NAV = [
  { to: "/accountant", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/accountant/enquiries", label: "Enquiries", icon: Inbox },
  { to: "/accountant/quotations", label: "Quotations", icon: FileText },
  { to: "/accountant/clients", label: "Clients", icon: UsersRound },
  { to: "/accountant/tasks", label: "Tasks & review", icon: ClipboardList },
  { to: "/accountant/work", label: "Workbench", icon: FlaskConical },
  { to: "/accountant/payment-connect", label: "Payment Connect", icon: Wallet },
  { to: "/accountant/tally", label: "Tally Integration", icon: FileSpreadsheet, end: true },
  { to: "/accountant/tally/migration", label: "Tally Data Migration", icon: Database },
  { to: "/accountant/billing", label: "Practice billing", icon: ReceiptIndianRupee },
  { to: "/accountant/reports", label: "Reports", icon: FileSearch },
  { to: "/accountant/documents", label: "Documents", icon: FileStack },
  { to: "/accountant/audit", label: "Audit trail", icon: ScrollText },
];

const JUNIOR_NAV = [
  { to: "/accountant", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/accountant/clients", label: "My clients", icon: Building2 },
  { to: "/accountant/tasks", label: "My tasks", icon: ClipboardList },
  { to: "/accountant/work", label: "Workbench", icon: FlaskConical },
  { to: "/accountant/payment-connect", label: "Payment Connect", icon: Wallet },
  { to: "/accountant/tally", label: "Tally Integration", icon: FileSpreadsheet, end: true },
  { to: "/accountant/tally/migration", label: "Tally Data Migration", icon: Database },
];

export function AccountantShell() {
  const { user, accounting, isSeniorAccountant, logout } = useAuth();
  const navigate = useNavigate();
  const nav = isSeniorAccountant ? SENIOR_NAV : JUNIOR_NAV;

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-white/5 bg-gradient-to-r from-[#052221] via-navy-950 to-[#0d2a3f] text-white">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
          <span className="flex h-9 w-9 shrink-0 overflow-hidden rounded-xl shadow-lg ring-1 ring-white/15">
            <img
              src="/branding/finovexa-mark.png"
              alt="FINOVEXA AI"
              className="h-full w-full object-cover object-[38%_38%]"
            />
          </span>
          <div className="min-w-0 leading-tight">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold tracking-tight">Accounting practice</p>
              <Badge
                tone="cyan"
                className={
                  isSeniorAccountant
                    ? "border-teal-300/30 bg-teal-400/10 text-teal-100"
                    : "border-cyan-300/30 bg-cyan-400/10 text-cyan-100"
                }
              >
                {isSeniorAccountant ? "SENIOR ACCOUNTANT" : "JUNIOR ACCOUNTANT"}
              </Badge>
            </div>
            <p className="truncate text-[10px] text-slate-400">
              Signed in as {user?.full_name} · {user?.email}
              {accounting?.display_name && accounting.display_name !== user?.full_name
                ? ` · ${accounting.display_name}`
                : ""}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] text-slate-300 lg:inline-flex">
              <ShieldCheck className="h-3 w-3 text-emerald-300" />
              {isSeniorAccountant ? "Practice-wide access" : "Assigned clients only"}
            </span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-brand-600 text-[11px] font-bold">
              {initials(user?.full_name || "Accountant")}
            </span>
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/accountant/login");
              }}
              className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 pb-2 sm:px-5" aria-label="Accounting practice">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "inline-flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-semibold transition",
                  isActive
                    ? "bg-white/12 text-white"
                    : "text-slate-400 hover:bg-white/5 hover:text-slate-100",
                )
              }
            >
              <item.icon className="h-3.5 w-3.5" aria-hidden />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
        <Suspense fallback={<PageSkeleton cards={4} />}>
          <Outlet />
        </Suspense>
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4 text-[10px] text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <BadgeCheck className="h-3 w-3" aria-hidden />
            Reports move through draft, senior review and delivery. Nothing is filed automatically.
          </span>
          <span>Every accounting action is written to the practice audit trail.</span>
        </footer>
      </main>
    </div>
  );
}
