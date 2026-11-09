import { Suspense, useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import {
  ArrowRight,
  ChevronDown,
  LayoutDashboard,
  Menu,
  Sparkles,
  X,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cn } from "../../lib/utils";
import { BrandLogo } from "../BrandLogo";
import { PublicLoading } from "./PublicUI";

type PrimaryLink = { to: string; label: string; end?: boolean; wideOnly?: boolean };

const PRIMARY_LINKS: PrimaryLink[] = [
  { to: "/home", label: "Home", end: true },
  { to: "/features", label: "Features" },
  { to: "/pricing", label: "Pricing" },
  { to: "/market-intelligence", label: "Market Intelligence" },
  { to: "/accounting", label: "Accounting" },
  { to: "/about", label: "About", wideOnly: true },
  { to: "/contact", label: "Contact", wideOnly: true },
];

function dashboardPath(role?: string) {
  if (role === "developer") return "/developer";
  if (role === "employee") return "/employee";
  if (role === "senior_accountant" || role === "junior_accountant") return "/accountant";
  if (role === "customer") return "/client";
  return "/";
}

export function PublicShell() {
  const { user } = useAuth();
  const { pathname, hash } = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setDrawerOpen(false);
    if (hash) {
      window.setTimeout(() => {
        document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 180);
    } else {
      window.scrollTo({ top: 0 });
    }
  }, [pathname, hash]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [drawerOpen]);

  return (
    <div className="relative min-h-screen overflow-x-clip bg-[#050b16] text-slate-300">
      <div
        className="pointer-events-none fixed inset-0 z-0"
        aria-hidden
        style={{
          background:
            "radial-gradient(1100px 600px at 8% -12%, rgba(36,120,240,0.18), transparent 62%), radial-gradient(900px 520px at 96% -6%, rgba(139,92,246,0.14), transparent 60%), radial-gradient(800px 600px at 60% 110%, rgba(14,165,183,0.1), transparent 60%)",
        }}
      />
      <div
        className="pointer-events-none fixed inset-0 z-0 opacity-[0.035]"
        aria-hidden
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.7) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.7) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage: "radial-gradient(ellipse at 50% 0%, black 20%, transparent 72%)",
          WebkitMaskImage: "radial-gradient(ellipse at 50% 0%, black 20%, transparent 72%)",
        }}
      />

      <header className="fixed inset-x-0 top-0 z-40 border-b border-white/[0.06] bg-[#050b16]/85 backdrop-blur-xl">
        <div className="mx-auto flex h-16 w-full max-w-7xl items-center gap-4 px-5 sm:px-8">
          <Link to="/home" className="shrink-0" aria-label="FINOVEXA AI home">
            <BrandLogo subtitle="Business intelligence" subtitleClassName="hidden text-slate-500 sm:block" />
          </Link>

          <nav className="ml-auto hidden items-center gap-1 lg:flex" aria-label="Main navigation">
            {PRIMARY_LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    "rounded-lg px-2.5 py-2 text-[12.5px] font-medium transition xl:px-3",
                    link.wideOnly && "hidden xl:inline-block",
                    isActive ? "text-white" : "text-slate-400 hover:text-white",
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2 lg:ml-3">
            {user ? (
              <Link
                to={dashboardPath(user.role)}
                className="hidden items-center gap-1.5 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2 text-xs font-semibold text-white shadow-[0_12px_30px_-16px_rgba(36,120,240,0.9)] transition hover:brightness-110 sm:inline-flex"
              >
                <LayoutDashboard className="h-3.5 w-3.5" aria-hidden /> Open dashboard
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="hidden rounded-lg px-3 py-2 text-[12.5px] font-medium text-slate-300 transition hover:text-white sm:block"
                >
                  Login
                </Link>
                <Link
                  to="/register"
                  className="hidden items-center gap-1.5 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2 text-xs font-semibold text-white shadow-[0_12px_30px_-16px_rgba(36,120,240,0.9)] transition hover:brightness-110 sm:inline-flex"
                >
                  Get Started <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </Link>
              </>
            )}
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="rounded-lg border border-white/10 p-2 text-slate-300 transition hover:bg-white/5 hover:text-white lg:hidden"
              aria-label="Open menu"
              aria-expanded={drawerOpen}
            >
              <Menu className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Site menu">
          <button
            type="button"
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close menu"
          />
          <div
            ref={drawerRef}
            className="absolute inset-y-0 right-0 flex w-[86%] max-w-sm animate-slide-in-right flex-col border-l border-white/10 bg-[#070f1d]"
          >
            <div className="flex h-16 items-center justify-between border-b border-white/10 px-5">
              <BrandLogo subtitle="Business intelligence" size="sm" />
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                className="rounded-lg border border-white/10 p-2 text-slate-300"
                aria-label="Close menu"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto px-4 py-4" aria-label="Mobile navigation">
              {PRIMARY_LINKS.map((link) => (
                <NavLink
                  key={link.to}
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) =>
                    cn(
                      "block rounded-lg px-3 py-3 text-sm transition",
                      isActive
                        ? "bg-white/[0.06] font-semibold text-white"
                        : "text-slate-300 hover:bg-white/5 hover:text-white",
                    )
                  }
                >
                  {link.label}
                </NavLink>
              ))}
            </nav>
            <div className="space-y-2 border-t border-white/10 p-4">
              {user ? (
                <Link
                  to={dashboardPath(user.role)}
                  className="flex items-center justify-center gap-1.5 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-xs font-semibold text-white"
                >
                  <LayoutDashboard className="h-3.5 w-3.5" aria-hidden /> Open dashboard
                </Link>
              ) : (
                <>
                  <Link
                    to="/register"
                    className="flex items-center justify-center gap-1.5 rounded-xl bg-[linear-gradient(135deg,#1f6feb,#2f86f6_55%,#0ea5b7)] px-4 py-2.5 text-xs font-semibold text-white"
                  >
                    Get Started <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                  </Link>
                  <Link
                    to="/login"
                    className="flex items-center justify-center rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-slate-200"
                  >
                    Login
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <main className="relative z-10 pt-16">
        <Suspense fallback={<PublicLoading />}>
          <div key={pathname} className="animate-fade-in">
            <Outlet />
          </div>
        </Suspense>
      </main>

      <footer className="relative z-10 mt-20 border-t border-white/[0.07] bg-[#040912]/70">
        <div className="mx-auto grid w-full max-w-7xl gap-10 px-5 py-12 sm:px-8 lg:grid-cols-[1.4fr_1fr_1.1fr]">
          <div>
            <BrandLogo subtitle="Business intelligence" />
            <p className="mt-4 max-w-xs text-xs leading-relaxed text-slate-500">
              Smarter Finance. Stronger Business. One intelligent workspace for accounting, payments,
              inventory, performance and growth opportunities.
            </p>
            <p className="mt-4 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-[10px] text-slate-500">
              <Sparkles className="h-3 w-3 text-brand-300" aria-hidden /> AI-assisted, human-approved
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Platform</p>
            <ul className="mt-3 space-y-2 text-xs">
              {[
                { to: "/features", label: "Features" },
                { to: "/pricing", label: "Pricing" },
                { to: "/market-intelligence", label: "Market Intelligence" },
                { to: "/accounting", label: "Accounting Services" },
                { to: "/about", label: "About FINOVEXA" },
                { to: "/contact", label: "Contact" },
              ].map((item) => (
                <li key={item.to}>
                  <Link to={item.to} className="text-slate-400 transition hover:text-white">
                    {item.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Contact</p>
            <ul className="mt-3 space-y-2 text-xs text-slate-400">
              <li>
                <Link to="/contact" className="text-slate-400 transition hover:text-white">
                  Send a message
                </Link>
              </li>
              <li>
                <Link to="/client/login" className="text-slate-500 transition hover:text-slate-300">
                  Client portal
                </Link>
              </li>
              <li>
                <Link to="/accountant/login" className="text-slate-500 transition hover:text-slate-300">
                  Accountant sign-in
                </Link>
              </li>
              <li>
                <Link to="/developer/login" className="text-slate-500 transition hover:text-slate-300">
                  Developer console
                </Link>
              </li>
            </ul>
          </div>
        </div>
        <div className="border-t border-white/[0.06]">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-2 px-5 py-5 text-[10.5px] leading-relaxed text-slate-600 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
            <p>© {new Date().getFullYear()} FINOVEXA AI. All rights reserved.</p>
            <p className="max-w-2xl">
              Market information is informational only and is not investment advice. Historical
              performance does not guarantee future results. Payments run in sandbox where configured.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
