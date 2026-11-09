import { Suspense } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { Code2, LogOut, ShieldCheck } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { initials } from "../../lib/utils";
import { Badge, PageSkeleton } from "../ui";
import { BrandLogo } from "../BrandLogo";

export function DeveloperShell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-white/5 bg-gradient-to-r from-slate-950 via-[#0b1220] to-[#1c1917] text-white">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3 sm:px-6">
          <BrandLogo
            size="sm"
            subtitle="Developer console"
            subtitleClassName="text-amber-300/80"
          />
          <Badge tone="amber" className="border-amber-300/30 bg-amber-400/10 text-amber-100">
            DEVELOPER CONSOLE
          </Badge>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-[10px] text-slate-400">
              Signed in as {user?.full_name} · {user?.email}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-emerald-300/20 bg-emerald-400/10 px-2.5 py-1 text-[10px] text-emerald-100 sm:inline-flex">
              <ShieldCheck className="h-3 w-3" /> Owner ledgers blocked
            </span>
            <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] text-slate-300 md:inline-flex">
              <Code2 className="h-3 w-3" /> Least privilege
            </span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-amber-400 to-orange-600 text-[11px] font-bold text-slate-950">
              {initials(user?.full_name || "Developer")}
            </span>
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/developer/login");
              }}
              className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <Suspense fallback={<PageSkeleton cards={3} />}>
          <Outlet />
        </Suspense>
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4 text-[10px] text-slate-400">
          <span>Developer actions are audited. Credentials never appear in logs or API responses.</span>
          <span>No access to owner cash, invoices, approvals, payments or market positions.</span>
        </footer>
      </main>
    </div>
  );
}
