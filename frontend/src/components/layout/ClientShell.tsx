import { Suspense } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { Building2, LogOut, LockKeyhole, ShieldCheck } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { initials } from "../../lib/utils";
import { Badge, PageSkeleton } from "../ui";

export function ClientShell() {
  const { user, accounting, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="border-b border-white/5 bg-gradient-to-r from-[#052221] via-navy-950 to-[#0d2a3f] text-white">
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
              <p className="truncate text-sm font-semibold tracking-tight">
                {accounting?.client?.business_name || "Client portal"}
              </p>
              <Badge tone="cyan" className="border-teal-300/30 bg-teal-400/10 text-teal-100">
                CLIENT PORTAL
              </Badge>
            </div>
            <p className="truncate text-[10px] text-slate-400">
              Signed in as {user?.full_name} · {user?.email}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[10px] text-slate-300 sm:inline-flex">
              <LockKeyhole className="h-3 w-3 text-emerald-300" /> Only your engagement
            </span>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-teal-400 to-brand-600 text-[11px] font-bold">
              {initials(user?.full_name || "Client")}
            </span>
            <button
              type="button"
              onClick={async () => {
                await logout();
                navigate("/client/login");
              }}
              className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:bg-white/10 hover:text-white"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 pb-3 text-[10px] text-slate-400 sm:px-6">
          <Building2 className="h-3 w-3" aria-hidden />
          <span>
            {accounting?.client
              ? `${accounting.client.code} · ${accounting.client.status.replace(/_/g, " ")}`
              : "Engagement not linked yet"}
          </span>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6">
        <Suspense fallback={<PageSkeleton cards={3} />}>
          <Outlet />
        </Suspense>
        <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4 text-[10px] text-slate-400">
          <span className="inline-flex items-center gap-1.5">
            <ShieldCheck className="h-3 w-3" aria-hidden />
            Documents are stored per engagement and served only to authorised users.
          </span>
          <span>You cannot see another client&apos;s records.</span>
        </footer>
      </main>
    </div>
  );
}
