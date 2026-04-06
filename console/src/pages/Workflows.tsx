import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

function statusVariant(status: string) {
  const normalized = status.toUpperCase();
  if (normalized.includes("FAIL") || normalized.includes("ERROR")) return "danger" as const;
  if (normalized.includes("WAIT") || normalized.includes("PENDING")) return "warning" as const;
  if (normalized.includes("DONE") || normalized.includes("SUCCESS") || normalized.includes("COMPLETED")) {
    return "success" as const;
  }
  return "info" as const;
}

export default function Workflows() {
  const [statusFilter, setStatusFilter] = useState("");
  const { data: runs = [] } = useQuery({
    queryKey: ["workflow-runs", statusFilter],
    queryFn: () => adminApi.runs(statusFilter ? { status: statusFilter, limit: 100 } : { limit: 100 }),
    refetchInterval: 15000,
  });

  return (
    <>
      <PageHeader
        title="Workflow Runs"
        subtitle="Recent orchestration runs with status, initiator, and recency."
        action={
          <input
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            placeholder="Filter status"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-200 outline-none ring-amber-500/40 focus:ring"
          />
        }
      />

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full text-left text-xs">
          <thead className="border-b border-slate-800 bg-slate-950/80 text-[10px] uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th className="px-3 py-2">Run ID</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Workflow</th>
              <th className="px-3 py-2">Initiated By</th>
              <th className="px-3 py-2">Started</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                  No runs found.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.run_id} className="border-b border-slate-900/80 hover:bg-slate-950/60">
                  <td className="px-3 py-2 font-mono text-[10px] text-amber-300">{run.run_id}</td>
                  <td className="px-3 py-2">
                    <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                  </td>
                  <td className="px-3 py-2 text-slate-300">{run.workflow_name}</td>
                  <td className="px-3 py-2 text-slate-400">{run.initiated_by}</td>
                  <td className="px-3 py-2 text-[10px] text-slate-500">
                    {formatDistanceToNow(new Date(run.created_at), { addSuffix: true })}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </>
  );
}
