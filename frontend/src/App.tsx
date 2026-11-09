import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import { AppShell } from "./components/layout/AppShell";
import { EmployeeShell } from "./components/layout/EmployeeShell";
import { DeveloperShell } from "./components/layout/DeveloperShell";
import { AccountantShell } from "./components/layout/AccountantShell";
import { ClientShell } from "./components/layout/ClientShell";
import { PublicShell } from "./components/public/PublicShell";
import { PageSkeleton } from "./components/ui";
import { AuthPage } from "./pages/AuthPage";

const OverviewPage = lazy(() => import("./pages/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const GstBillingPage = lazy(() => import("./pages/GstBillingPage").then((m) => ({ default: m.GstBillingPage })));
const RecoveryPage = lazy(() => import("./pages/RecoveryPage").then((m) => ({ default: m.RecoveryPage })));
const TaxCenterPage = lazy(() => import("./pages/TaxCenterPage").then((m) => ({ default: m.TaxCenterPage })));
const CashflowPage = lazy(() => import("./pages/CashflowPage").then((m) => ({ default: m.CashflowPage })));
const MarketPage = lazy(() => import("./pages/MarketPage").then((m) => ({ default: m.MarketPage })));
const ResearchPage = lazy(() => import("./pages/ResearchPage").then((m) => ({ default: m.ResearchPage })));
const AskPage = lazy(() => import("./pages/AskPage").then((m) => ({ default: m.AskPage })));
const ApprovalsPage = lazy(() => import("./pages/ApprovalsPage").then((m) => ({ default: m.ApprovalsPage })));
const PaymentsPage = lazy(() => import("./pages/PaymentsPage").then((m) => ({ default: m.PaymentsPage })));
const PaymentConnectPage = lazy(() =>
  import("./pages/PaymentConnectPage").then((m) => ({ default: m.PaymentConnectPage })),
);
const AuditPage = lazy(() => import("./pages/AuditPage").then((m) => ({ default: m.AuditPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const TeamPage = lazy(() => import("./pages/TeamPage").then((m) => ({ default: m.TeamPage })));
const EmployeeLoginPage = lazy(() =>
  import("./pages/EmployeeLoginPage").then((m) => ({ default: m.EmployeeLoginPage })),
);
const EmployeeOverviewPage = lazy(() =>
  import("./pages/EmployeeOverviewPage").then((m) => ({ default: m.EmployeeOverviewPage })),
);
const EmployeeEntriesPage = lazy(() =>
  import("./pages/EmployeeEntriesPage").then((m) => ({ default: m.EmployeeEntriesPage })),
);
const EmployeeInvoicesPage = lazy(() =>
  import("./pages/EmployeeInvoicesPage").then((m) => ({ default: m.EmployeeInvoicesPage })),
);
const DeveloperLoginPage = lazy(() =>
  import("./pages/DeveloperLoginPage").then((m) => ({ default: m.DeveloperLoginPage })),
);
const DeveloperConsolePage = lazy(() =>
  import("./pages/DeveloperConsolePage").then((m) => ({ default: m.DeveloperConsolePage })),
);
const AccountingServicesPage = lazy(() =>
  import("./pages/public/AccountingServicesPage").then((m) => ({ default: m.AccountingServicesPage })),
);
const AccountantLoginPage = lazy(() =>
  import("./pages/accounting/AccountantLoginPage").then((m) => ({ default: m.AccountantLoginPage })),
);
const ClientLoginPage = lazy(() =>
  import("./pages/accounting/ClientLoginPage").then((m) => ({ default: m.ClientLoginPage })),
);
const AccountantDashboardPage = lazy(() =>
  import("./pages/accounting/AccountantDashboardPage").then((m) => ({
    default: m.AccountantDashboardPage,
  })),
);
const AccountantEnquiriesPage = lazy(() =>
  import("./pages/accounting/AccountantEnquiriesPage").then((m) => ({
    default: m.AccountantEnquiriesPage,
  })),
);
const AccountantQuotationsPage = lazy(() =>
  import("./pages/accounting/AccountantQuotationsPage").then((m) => ({
    default: m.AccountantQuotationsPage,
  })),
);
const AccountantClientsPage = lazy(() =>
  import("./pages/accounting/AccountantClientsPage").then((m) => ({ default: m.AccountantClientsPage })),
);
const AccountantClientDetailPage = lazy(() =>
  import("./pages/accounting/AccountantClientDetailPage").then((m) => ({
    default: m.AccountantClientDetailPage,
  })),
);
const AccountantTasksPage = lazy(() =>
  import("./pages/accounting/AccountantTasksPage").then((m) => ({ default: m.AccountantTasksPage })),
);
const AccountantWorkPage = lazy(() =>
  import("./pages/accounting/AccountantWorkPage").then((m) => ({ default: m.AccountantWorkPage })),
);
const TallyIntegrationPage = lazy(() =>
  import("./pages/accounting/TallyIntegrationPage").then((m) => ({
    default: m.TallyIntegrationPage,
  })),
);
const TallyMigrationPage = lazy(() =>
  import("./pages/accounting/TallyMigrationPage").then((m) => ({
    default: m.TallyMigrationPage,
  })),
);
const AccountantBillingPage = lazy(() =>
  import("./pages/accounting/AccountantBillingPage").then((m) => ({ default: m.AccountantBillingPage })),
);
const AccountantReportsPage = lazy(() =>
  import("./pages/accounting/AccountantReportsPage").then((m) => ({ default: m.AccountantReportsPage })),
);
const AccountantDocumentsPage = lazy(() =>
  import("./pages/accounting/AccountantDocumentsPage").then((m) => ({
    default: m.AccountantDocumentsPage,
  })),
);
const AccountantAuditPage = lazy(() =>
  import("./pages/accounting/AccountantAuditPage").then((m) => ({ default: m.AccountantAuditPage })),
);
const ClientPortalPage = lazy(() =>
  import("./pages/accounting/ClientPortalPage").then((m) => ({ default: m.ClientPortalPage })),
);
const HomePage = lazy(() => import("./pages/public/HomePage").then((m) => ({ default: m.HomePage })));
const FeaturesPage = lazy(() =>
  import("./pages/public/FeaturesPage").then((m) => ({ default: m.FeaturesPage })),
);
const PricingPage = lazy(() =>
  import("./pages/public/PricingPage").then((m) => ({ default: m.PricingPage })),
);
const AboutPage = lazy(() => import("./pages/public/AboutPage").then((m) => ({ default: m.AboutPage })));
const ContactPage = lazy(() =>
  import("./pages/public/ContactPage").then((m) => ({ default: m.ContactPage })),
);
const MarketIntelligencePage = lazy(() =>
  import("./pages/public/MarketIntelligencePage").then((m) => ({
    default: m.MarketIntelligencePage,
  })),
);

function LoadingScreen({ dark = false }: { dark?: boolean }) {
  return (
    <div
      className={
        dark
          ? "flex min-h-screen items-center justify-center bg-navy-950 text-sm text-slate-400"
          : "flex min-h-screen items-center justify-center bg-slate-50 p-6"
      }
    >
      {dark ? (
        "Loading workspace…"
      ) : (
        <div className="w-full max-w-4xl">
          <PageSkeleton cards={4} />
        </div>
      )}
    </div>
  );
}

function OwnerRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) return <Navigate to="/home" replace state={{ from: location.pathname }} />;
  if (user.role === "employee") return <Navigate to="/employee" replace />;
  if (user.role === "developer") return <Navigate to="/developer" replace />;
  if (user.role === "senior_accountant" || user.role === "junior_accountant")
    return <Navigate to="/accountant" replace />;
  if (user.role === "customer") return <Navigate to="/client" replace />;
  return <AppShell />;
}

function OwnerGuest({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen dark />;
  if (user) {
    if (user.role === "employee") return <Navigate to="/employee" replace />;
    if (user.role === "developer") return <Navigate to="/developer" replace />;
    if (user.role === "senior_accountant" || user.role === "junior_accountant")
      return <Navigate to="/accountant" replace />;
    if (user.role === "customer") return <Navigate to="/client" replace />;
    const state = location.state as { from?: string } | null;
    const target = state?.from?.startsWith("/employee") ? "/" : state?.from || "/";
    return <Navigate to={target} replace />;
  }
  return children;
}

function EmployeeRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) {
    return <Navigate to="/employee/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role === "owner") return <Navigate to="/" replace />;
  if (user.role === "developer") return <Navigate to="/developer" replace />;
  if (user.role === "senior_accountant" || user.role === "junior_accountant")
    return <Navigate to="/accountant" replace />;
  if (user.role === "customer") return <Navigate to="/client" replace />;
  return <EmployeeShell />;
}

function EmployeeGuest({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen dark />;
  if (user) {
    if (user.role === "owner") return <Navigate to="/" replace />;
    if (user.role === "developer") return <Navigate to="/developer" replace />;
    if (user.role === "senior_accountant" || user.role === "junior_accountant")
      return <Navigate to="/accountant" replace />;
    if (user.role === "customer") return <Navigate to="/client" replace />;
    const state = location.state as { from?: string } | null;
    const target = state?.from?.startsWith("/employee") ? state.from : "/employee";
    return <Navigate to={target} replace />;
  }
  return children;
}

function DeveloperRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) {
    return <Navigate to="/developer/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role === "owner") return <Navigate to="/" replace />;
  if (user.role === "employee") return <Navigate to="/employee" replace />;
  if (user.role === "senior_accountant" || user.role === "junior_accountant")
    return <Navigate to="/accountant" replace />;
  if (user.role === "customer") return <Navigate to="/client" replace />;
  return <DeveloperShell />;
}

function DeveloperGuest({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingScreen dark />;
  if (user) {
    if (user.role === "owner") return <Navigate to="/" replace />;
    if (user.role === "employee") return <Navigate to="/employee" replace />;
    if (user.role === "senior_accountant" || user.role === "junior_accountant")
      return <Navigate to="/accountant" replace />;
    if (user.role === "customer") return <Navigate to="/client" replace />;
    return <Navigate to="/developer" replace />;
  }
  return children;
}

function AccountantRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) {
    return <Navigate to="/accountant/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role === "senior_accountant" || user.role === "junior_accountant") {
    return <AccountantShell />;
  }
  if (user.role === "owner") return <Navigate to="/" replace />;
  if (user.role === "employee") return <Navigate to="/employee" replace />;
  if (user.role === "developer") return <Navigate to="/developer" replace />;
  return <Navigate to="/client" replace />;
}

function AccountantGuest({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingScreen dark />;
  if (user) {
    if (user.role === "senior_accountant" || user.role === "junior_accountant") {
      return <Navigate to="/accountant" replace />;
    }
    if (user.role === "owner") return <Navigate to="/" replace />;
    if (user.role === "employee") return <Navigate to="/employee" replace />;
    if (user.role === "developer") return <Navigate to="/developer" replace />;
    return <Navigate to="/client" replace />;
  }
  return children;
}

function ClientRoute() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <LoadingScreen />;
  if (!user) {
    return <Navigate to="/client/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role === "customer") return <ClientShell />;
  if (user.role === "owner") return <Navigate to="/" replace />;
  if (user.role === "employee") return <Navigate to="/employee" replace />;
  if (user.role === "developer") return <Navigate to="/developer" replace />;
  return <Navigate to="/accountant" replace />;
}

function ClientGuest({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingScreen dark />;
  if (user) {
    if (user.role === "customer") return <Navigate to="/client" replace />;
    if (user.role === "owner") return <Navigate to="/" replace />;
    if (user.role === "employee") return <Navigate to="/employee" replace />;
    if (user.role === "developer") return <Navigate to="/developer" replace />;
    return <Navigate to="/accountant" replace />;
  }
  return children;
}

function SeniorOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <LoadingScreen />;
  if (user?.role !== "senior_accountant") return <Navigate to="/accountant" replace />;
  return <>{children}</>;
}

function NotFound() {
  const { user } = useAuth();
  const home =
    user?.role === "developer"
      ? "/developer"
      : user?.role === "employee"
        ? "/employee"
        : user?.role === "senior_accountant" || user?.role === "junior_accountant"
          ? "/accountant"
          : user?.role === "customer"
            ? "/client"
            : user?.role === "owner"
              ? "/"
              : "/home";
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">404</p>
      <h1 className="text-xl font-semibold text-ink-900">That page does not exist.</h1>
      <a href={home} className="text-sm font-semibold text-brand-600 hover:text-brand-700">
        Return to the{" "}
        {user?.role === "developer"
          ? "developer console"
          : user?.role === "employee"
            ? "employee workspace"
            : user?.role === "senior_accountant" || user?.role === "junior_accountant"
              ? "practice workspace"
              : user?.role === "customer"
                ? "client portal"
                : "overview"}
      </a>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <OwnerGuest>
            <AuthPage mode="login" />
          </OwnerGuest>
        }
      />
      <Route
        path="/register"
        element={
          <OwnerGuest>
            <AuthPage mode="register" />
          </OwnerGuest>
        }
      />
      <Route
        path="/employee/login"
        element={
          <EmployeeGuest>
            <Suspense fallback={<LoadingScreen dark />}>
              <EmployeeLoginPage />
            </Suspense>
          </EmployeeGuest>
        }
      />
      <Route
        path="/developer/login"
        element={
          <DeveloperGuest>
            <Suspense fallback={<LoadingScreen dark />}>
              <DeveloperLoginPage />
            </Suspense>
          </DeveloperGuest>
        }
      />
      <Route
        path="/accountant/login"
        element={
          <AccountantGuest>
            <Suspense fallback={<LoadingScreen dark />}>
              <AccountantLoginPage />
            </Suspense>
          </AccountantGuest>
        }
      />
      <Route
        path="/client/login"
        element={
          <ClientGuest>
            <Suspense fallback={<LoadingScreen dark />}>
              <ClientLoginPage />
            </Suspense>
          </ClientGuest>
        }
      />

      <Route element={<PublicShell />}>
        <Route path="/home" element={<HomePage />} />
        <Route path="/features" element={<FeaturesPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/market-intelligence" element={<MarketIntelligencePage />} />
        <Route
          path="/accounting"
          element={
            <Suspense fallback={<LoadingScreen dark />}>
              <AccountingServicesPage />
            </Suspense>
          }
        />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/contact" element={<ContactPage />} />
      </Route>

      <Route element={<OwnerRoute />}>
        <Route index element={<OverviewPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/billing" element={<GstBillingPage />} />
        <Route path="/tax" element={<TaxCenterPage />} />
        <Route path="/recovery" element={<RecoveryPage />} />
        <Route path="/cash-flow" element={<CashflowPage />} />
        <Route path="/markets" element={<MarketPage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/payments" element={<PaymentsPage />} />
        <Route path="/payment-connect" element={<PaymentConnectPage mode="owner" />} />
        <Route path="/team" element={<TeamPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>

      <Route element={<EmployeeRoute />}>
        <Route path="/employee" element={<EmployeeOverviewPage />} />
        <Route path="/employee/entries" element={<EmployeeEntriesPage />} />
        <Route path="/employee/invoices" element={<EmployeeInvoicesPage />} />
      </Route>

      <Route element={<DeveloperRoute />}>
        <Route path="/developer" element={<DeveloperConsolePage />} />
      </Route>

      <Route element={<AccountantRoute />}>
        <Route path="/accountant" element={<AccountantDashboardPage />} />
        <Route
          path="/accountant/enquiries"
          element={
            <SeniorOnly>
              <AccountantEnquiriesPage />
            </SeniorOnly>
          }
        />
        <Route
          path="/accountant/quotations"
          element={
            <SeniorOnly>
              <AccountantQuotationsPage />
            </SeniorOnly>
          }
        />
        <Route path="/accountant/clients" element={<AccountantClientsPage />} />
        <Route path="/accountant/clients/:clientId" element={<AccountantClientDetailPage />} />
        <Route path="/accountant/tasks" element={<AccountantTasksPage />} />
        <Route path="/accountant/work" element={<AccountantWorkPage />} />
        <Route path="/accountant/payment-connect" element={<PaymentConnectPage mode="accountant" />} />
        <Route path="/accountant/tally" element={<TallyIntegrationPage />} />
        <Route path="/accountant/tally/migration" element={<TallyMigrationPage />} />
        <Route
          path="/accountant/billing"
          element={
            <SeniorOnly>
              <AccountantBillingPage />
            </SeniorOnly>
          }
        />
        <Route
          path="/accountant/reports"
          element={
            <SeniorOnly>
              <AccountantReportsPage />
            </SeniorOnly>
          }
        />
        <Route
          path="/accountant/documents"
          element={
            <SeniorOnly>
              <AccountantDocumentsPage />
            </SeniorOnly>
          }
        />
        <Route
          path="/accountant/audit"
          element={
            <SeniorOnly>
              <AccountantAuditPage />
            </SeniorOnly>
          }
        />
      </Route>

      <Route element={<ClientRoute />}>
        <Route path="/client" element={<ClientPortalPage />} />
      </Route>

      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
