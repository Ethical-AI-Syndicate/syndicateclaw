import { type ReactNode, useMemo } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Activity,
  Bot,
  CheckSquare,
  ClipboardList,
  Database,
  GitBranch,
  Home,
  Key,
  Settings,
  Shield,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { adminApi } from "@/api/client";

type BadgeVariant = "default" | "success" | "warning" | "danger" | "info";

export function Badge({
  children,
  variant = "default",
}: {
  children: ReactNode;
  variant?: BadgeVariant;
}) {
  const colors: Record<BadgeVariant, string> = {
    default: "bg-slate-700 text-slate-200 border-slate-600",
    success: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
    warning: "bg-amber-900/40 text-amber-300 border-amber-700",
    danger: "bg-rose-900/40 text-rose-300 border-rose-700",
    info: "bg-cyan-900/40 text-cyan-300 border-cyan-700",
  };
  return (
    <span className={`rounded border px-2 py-0.5 text-[10px] uppercase tracking-wider ${colors[variant]}`}>
      {children}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <section className={`rounded border border-slate-800 bg-slate-900/70 p-4 shadow-xl shadow-black/20 ${className}`}>
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3 border-b border-slate-800 pb-3">
      <div>
        <h1 className="text-sm font-bold uppercase tracking-widest text-amber-300">{title}</h1>
        {subtitle ? <p className="mt-1 text-xs text-slate-400">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function StatCard({
  title,
  value,
  hint,
}: {
  title: string;
  value: string | number;
  hint?: string;
}) {
  return (
    <Card className="p-3">
      <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">{title}</p>
      <p className="mt-2 text-2xl font-bold text-amber-300">{value}</p>
      {hint ? <p className="mt-1 text-[10px] text-slate-500">{hint}</p> : null}
    </Card>
  );
}

const navItems = [
  { icon: Home, label: "Home", path: "/console" },
  { icon: Bot, label: "Connectors", path: "/console/connectors" },
  { icon: CheckSquare, label: "Approvals", path: "/console/approvals" },
  { icon: GitBranch, label: "Workflows", path: "/console/workflows" },
  { icon: Activity, label: "Providers", path: "/console/providers" },
  { icon: Shield, label: "Policies", path: "/console/policies" },
  { icon: Database, label: "Memory", path: "/console/memory" },
  { icon: ClipboardList, label: "Audit", path: "/console/audit" },
  { icon: Key, label: "API Keys", path: "/console/api-keys" },
  { icon: Settings, label: "Settings", path: "/console/settings" },
];

export function Layout() {
  const navigate = useNavigate();
  const { data: approvals = [] } = useQuery({
    queryKey: ["approval-count"],
    queryFn: adminApi.approvalQueue,
    refetchInterval: 15000,
  });
  const pendingApprovals = useMemo(
    () => approvals.filter((item) => item.status.toUpperCase() === "PENDING").length,
    [approvals]
  );

  return (
    <div className="min-h-screen bg-slate-950 text-xs text-slate-200">
      <div className="grid min-h-screen grid-cols-1 md:grid-cols-[14rem_1fr]">
        <aside className="w-full border-r border-slate-800 bg-slate-900/95 p-4 md:w-56">
          <Link to="/console" className="mb-6 block">
            <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">SyndicateClaw</p>
            <p className="mt-1 text-sm font-bold text-amber-400">Command Console</p>
          </Link>

          <nav className="space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isApprovals = item.path === "/console/approvals";
              return (
                <NavLink
                  key={item.path}
                  to={item.path}
                  className={({ isActive }) =>
                    [
                      "flex items-center justify-between rounded border px-3 py-2 text-xs transition",
                      isActive
                        ? "border-amber-700 bg-slate-950 text-amber-400"
                        : "border-transparent text-slate-300 hover:border-slate-700 hover:bg-slate-950/80",
                    ].join(" ")
                  }
                >
                  <span className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5" />
                    {item.label}
                  </span>
                  {isApprovals && pendingApprovals > 0 ? <Badge variant="warning">{pendingApprovals}</Badge> : null}
                </NavLink>
              );
            })}
          </nav>

          <button
            type="button"
            onClick={() => {
              localStorage.removeItem("sc_api_key");
              navigate("/console/login");
            }}
            className="mt-6 w-full rounded border border-slate-700 px-3 py-2 text-[10px] uppercase tracking-[0.2em] text-slate-400 hover:border-amber-700 hover:text-amber-400"
          >
            Logout
          </button>
        </aside>

        <main className="p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
