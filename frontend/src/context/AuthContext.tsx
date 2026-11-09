import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, getToken, post, setToken } from "../lib/api";
import type {
  AccountingContext,
  AuthResponse,
  BusinessSummary,
  MeResponse,
  Profile,
  User,
} from "../lib/types";

interface AuthContextValue {
  user: User | null;
  profile: Profile | null;
  business: BusinessSummary | null;
  accounting: AccountingContext | null;
  demoMode: boolean;
  loading: boolean;
  isOwner: boolean;
  isEmployee: boolean;
  isDeveloper: boolean;
  isAccountant: boolean;
  isSeniorAccountant: boolean;
  isJuniorAccountant: boolean;
  isCustomer: boolean;
  login: (email: string, password: string) => Promise<void>;
  employeeLogin: (email: string, password: string) => Promise<void>;
  developerLogin: (email: string, password: string) => Promise<void>;
  accountantLogin: (email: string, password: string) => Promise<void>;
  customerLogin: (email: string, password: string) => Promise<void>;
  register: (payload: {
    email: string;
    password: string;
    full_name: string;
    business_name: string;
    currency: string;
  }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  setProfile: (profile: Profile) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [business, setBusiness] = useState<BusinessSummary | null>(null);
  const [accounting, setAccounting] = useState<AccountingContext | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [loading, setLoading] = useState(true);

  const clearSession = useCallback(() => {
    setToken(null);
    setUser(null);
    setProfile(null);
    setBusiness(null);
    setAccounting(null);
    setDemoMode(false);
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setProfile(null);
      setBusiness(null);
      setAccounting(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<MeResponse>("/auth/me");
      setUser(me.user);
      setProfile(me.profile);
      setBusiness(me.business);
      setAccounting(me.accounting);
      setDemoMode(me.demo_mode);
    } catch {
      clearSession();
    } finally {
      setLoading(false);
    }
  }, [clearSession]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setProfile(null);
      setBusiness(null);
      setAccounting(null);
      setDemoMode(false);
    };
    window.addEventListener("finovexa:unauthorized", onUnauthorized);
    return () => window.removeEventListener("finovexa:unauthorized", onUnauthorized);
  }, []);

  const consumeAuth = useCallback((result: AuthResponse) => {
    setToken(result.access_token);
    setUser(result.user);
    setProfile(result.profile);
    setBusiness(result.business);
    const role = result.user.role;
    setAccounting(
      role === "senior_accountant" || role === "junior_accountant" || role === "customer"
        ? {
            portal: role === "customer" ? "customer" : "accountant",
            role,
            display_name: result.user.full_name,
          }
        : null,
    );
    setDemoMode(result.user.is_demo);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await post<AuthResponse>("/auth/login", { email, password }, { auth: false });
      consumeAuth(result);
    },
    [consumeAuth],
  );

  const employeeLogin = useCallback(
    async (email: string, password: string) => {
      const result = await post<AuthResponse>(
        "/auth/employee/login",
        { email, password },
        { auth: false },
      );
      consumeAuth(result);
    },
    [consumeAuth],
  );

  const developerLogin = useCallback(
    async (email: string, password: string) => {
      const result = await post<AuthResponse>(
        "/auth/developer/login",
        { email, password },
        { auth: false },
      );
      consumeAuth(result);
    },
    [consumeAuth],
  );

  const accountantLogin = useCallback(
    async (email: string, password: string) => {
      const result = await post<AuthResponse>(
        "/auth/accountant/login",
        { email, password },
        { auth: false },
      );
      consumeAuth(result);
    },
    [consumeAuth],
  );

  const customerLogin = useCallback(
    async (email: string, password: string) => {
      const result = await post<AuthResponse>(
        "/auth/customer/login",
        { email, password },
        { auth: false },
      );
      consumeAuth(result);
      await refresh();
    },
    [consumeAuth, refresh],
  );

  const register = useCallback(
    async (payload: {
      email: string;
      password: string;
      full_name: string;
      business_name: string;
      currency: string;
    }) => {
      const result = await post<AuthResponse>("/auth/register", payload, { auth: false });
      consumeAuth(result);
    },
    [consumeAuth],
  );

  const logout = useCallback(async () => {
    try {
      await post("/auth/logout");
    } catch {
      // A failed logout call must still clear the local session.
    }
    clearSession();
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      profile,
      business,
      accounting,
      demoMode,
      loading,
      isOwner: user?.role === "owner",
      isEmployee: user?.role === "employee",
      isDeveloper: user?.role === "developer",
      isAccountant: user?.role === "senior_accountant" || user?.role === "junior_accountant",
      isSeniorAccountant: user?.role === "senior_accountant",
      isJuniorAccountant: user?.role === "junior_accountant",
      isCustomer: user?.role === "customer",
      login,
      employeeLogin,
      developerLogin,
      accountantLogin,
      customerLogin,
      register,
      logout,
      refresh,
      setProfile,
    }),
    [
      user,
      profile,
      business,
      accounting,
      demoMode,
      loading,
      login,
      employeeLogin,
      developerLogin,
      accountantLogin,
      customerLogin,
      register,
      logout,
      refresh,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
