import { Suspense } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { FilePlus2, LogOut, ReceiptText, ShieldCheck, Sparkles } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cn, initials } from "../../lib/utils";
import { Badge, PageSkeleton } from "../ui";

const EMPLOYEE_NAV = [
  { to: "/employee", label: "My day", icon: Sparkles, end: true },
  { to: "/employee/entries", label: "Sales & purchases", icon: FilePlus2 },
  { to: "/employee/invoices", label: "Invoices", icon: ReceiptText },
];

export function EmployeeShell() {
  const { user, business, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-white/5 bg-gradient-to-r from-navy-950 via-navy-900 to-[#10294b] text-white">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <span className="flex h-9 w-9 shrink-0 overflow-hidden rounded-xl shadow-lg ring-1 ring-white/15">
            <img
              src="/branding/finovexa-mark.png"
              alt="FINOVEXA AI"
              className="h-full w-full object-cover object-[38%_38%]"
            />
          </span>
          <div className="min-w-0 leading-tight">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold tracking-tight">{business?.business_name || "Business workspace"}</p>
              <Badge tone="cyan" className="border-cyan-300/30 bg-cyan-400/10 text-cyan-100">
                EMPLOYEE PORTAL
              </Badge>
            </div>
            <p className="truncate text-[10px] text-slate-400">
              Signed in as {user?.full_name} · {user?.email}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] text-slate-300 sm:inline-flex">
              <ShieldCheck className="h-3 w-3 text-emerald-300" /> Owner dashboard blocked
            </span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-brand-600 text-[11px] font-bold">
              {initials(user?.full_name || "Employee")}
            </span>
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/employee/login");
              }}
              className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
        <nav className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-3 pb-2 sm:px-5" aria-label="Employee portal">
          {EMPLOYEE_NAV.map((item) => (
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

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <Suspense fallback={<PageSkeleton cards={3} />}>
          <Outlet />
        </Suspense>
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4 text-[10px] text-slate-400">
          <span>Employee entries are attributed to you and visible to the business owner immediately.</span>
          <span>No access to owner cash totals, approvals or market data.</span>
        </footer>
      </main>
    </div>
  );
}
