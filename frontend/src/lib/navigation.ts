import {
  BarChart3,
  CreditCard,
  Globe2,
  HandCoins,
  LayoutDashboard,
  LineChart,
  ReceiptText,
  ScrollText,
  Scale,
  Settings2,
  ShieldCheck,
  Sparkles,
  Users,
  Wallet,
  Waves,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
  hint?: string;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Command",
    items: [
      { to: "/", label: "Overview", icon: LayoutDashboard, end: true, hint: "Executive briefing" },
      { to: "/ask", label: "Ask FINOVEXA", icon: Sparkles, hint: "Grounded AI answers" },
    ],
  },
  {
    label: "Operations",
    items: [
      { to: "/analytics", label: "Business Analytics", icon: BarChart3, hint: "Revenue and margins" },
      { to: "/billing", label: "GST & Billing", icon: ReceiptText, hint: "Tax invoices and PDF" },
      { to: "/tax", label: "Tax Center", icon: Scale, hint: "GST and income-tax estimates" },
      { to: "/recovery", label: "Money Recovery", icon: HandCoins, hint: "Invoices and reminders" },
      { to: "/cash-flow", label: "Cash Flow", icon: Waves, hint: "7 / 30 / 90 day forecast" },
    ],
  },
  {
    label: "Markets",
    items: [
      { to: "/markets", label: "Market Intelligence", icon: Globe2, hint: "Metals, indices, equities" },
      { to: "/research", label: "Investment Research", icon: LineChart, hint: "Model signals and orders" },
    ],
  },
  {
    label: "Governance",
    items: [
      { to: "/team", label: "Team Entries", icon: Users, hint: "Employee portal activity" },
      { to: "/approvals", label: "Approval Center", icon: ShieldCheck, hint: "Human decisions" },
      { to: "/payments", label: "Payment Center", icon: CreditCard, hint: "PayPal and reconciliation" },
      { to: "/payment-connect", label: "Payment Connect", icon: Wallet, hint: "Provider sync and matching" },
      { to: "/audit", label: "Activity Log", icon: ScrollText, hint: "Immutable audit trail" },
    ],
  },
  {
    label: "System",
    items: [{ to: "/settings", label: "Settings & Integrations", icon: Settings2, hint: "Profile and providers" }],
  },
];

export const ALL_PAGES = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, group: group.label })),
);

export function pageForPath(pathname: string) {
  return ALL_PAGES.find((page) => (page.end ? pathname === page.to : pathname.startsWith(page.to)));
}
