import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

export default function Approvals() {
  const queryClient = useQueryClient();
  const { data: approvals = [], isLoading } = useQuery({
    queryKey: ["approvals"],
    queryFn: adminApi.approvalQueue,
    refetchInterval: 15000,
  });

  const decideMutation = useMutation({
    mutationFn: ({ id, accepted }: { id: string; accepted: boolean }) =>
      adminApi.decideApproval(id, accepted),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
      queryClient.invalidateQueries({ queryKey: ["approval-count"] });
    },
  });

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Review pending approvals and issue approve/reject decisions."
      />

      {isLoading ? <p className="text-xs text-slate-500">Loading queue...</p> : null}

      <div className="space-y-3">
        {approvals.length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">Queue is empty. New approval requests will appear here.</p>
          </Card>
        ) : (
          approvals.map((item) => (
            <Card key={item.id}>
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-amber-300">{item.action}</p>
                  <p className="mt-1 text-[10px] text-slate-500">ID: {item.id}</p>
                </div>
                <Badge variant={item.status === "PENDING" ? "warning" : "info"}>{item.status}</Badge>
              </div>

              <p className="mt-3 text-xs text-slate-300">Actor: {item.actor}</p>
              {item.reason ? <p className="mt-1 text-xs text-slate-400">{item.reason}</p> : null}
              <p className="mt-1 text-[10px] text-slate-600">
                {formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}
              </p>

              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  onClick={() => decideMutation.mutate({ id: item.id, accepted: true })}
                  className="rounded border border-emerald-700 bg-emerald-900/20 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-emerald-300 hover:bg-emerald-800/30"
                >
                  Approve
                </button>
                <button
                  type="button"
                  onClick={() => decideMutation.mutate({ id: item.id, accepted: false })}
                  className="rounded border border-rose-700 bg-rose-900/20 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-rose-300 hover:bg-rose-800/30"
                >
                  Reject
                </button>
              </div>
            </Card>
          ))
        )}
      </div>
    </>
  );
}
