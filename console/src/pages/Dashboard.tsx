import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader, StatCard } from "@/components/Layout";

export default function Dashboard() {
  const { data: metrics } = useQuery({
    queryKey: ["dashboard-metrics"],
    queryFn: adminApi.dashboard,
    refetchInterval: 30000,
  });
  const { data: connectors = [] } = useQuery({
    queryKey: ["dashboard-connectors"],
    queryFn: adminApi.connectors,
    refetchInterval: 30000,
  });
  const { data: approvals = [] } = useQuery({
    queryKey: ["dashboard-approvals"],
    queryFn: adminApi.approvalQueue,
    refetchInterval: 30000,
  });

  const m =
    metrics ??
    ({
      connectors_total: 0,
      connectors_connected: 0,
      connectors_errors: 0,
      pending_approvals: 0,
      workflow_runs_active: 0,
      memory_namespaces: 0,
    } as const);

  return (
    <>
      <PageHeader
        title="Operations Dashboard"
        subtitle="Platform pulse across connectors, approvals, and runtime workload."
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard title="Connectors" value={m.connectors_total} hint="registered" />
        <StatCard title="Connected" value={m.connectors_connected} hint="healthy sessions" />
        <StatCard title="Connector Errors" value={m.connectors_errors} hint="runtime failures" />
        <StatCard title="Pending Approvals" value={m.pending_approvals} hint="human gates" />
        <StatCard title="Active Workflow Runs" value={m.workflow_runs_active} hint="currently executing" />
        <StatCard title="Memory Namespaces" value={m.memory_namespaces} hint="logical stores" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <h2 className="mb-3 text-[11px] uppercase tracking-[0.2em] text-slate-400">Connector Status</h2>
          <div className="space-y-2">
            {connectors.length === 0 ? (
              <p className="text-xs text-slate-500">No connectors configured.</p>
            ) : (
              connectors.map((item) => (
                <div
                  key={item.platform}
                  className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/60 px-3 py-2"
                >
                  <div>
                    <p className="text-xs uppercase tracking-wider text-slate-200">{item.platform}</p>
                    <p className="text-[10px] text-slate-500">events={item.events_received} errors={item.errors}</p>
                  </div>
                  <Badge variant={item.connected ? "success" : "danger"}>
                    {item.connected ? "Connected" : "Disconnected"}
                  </Badge>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card>
          <h2 className="mb-3 text-[11px] uppercase tracking-[0.2em] text-slate-400">Approval Queue Snapshot</h2>
          <div className="space-y-2">
            {approvals.length === 0 ? (
              <p className="text-xs text-slate-500">No approvals are currently queued.</p>
            ) : (
              approvals.slice(0, 5).map((item) => (
                <div key={item.id} className="rounded border border-slate-800 bg-slate-950/60 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-xs text-amber-300">{item.action}</p>
                    <Badge variant={item.status === "PENDING" ? "warning" : "info"}>{item.status}</Badge>
                  </div>
                  <p className="mt-1 text-[10px] text-slate-500">{item.actor}</p>
                  <p className="mt-1 text-[10px] text-slate-600">
                    {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
                  </p>
                </div>
              ))
            )}
          </div>
        </Card>
      </div>
    </>
  );
}
