import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminApi } from "@/api/client";
import { Card, PageHeader } from "@/components/Layout";

export default function Memory() {
  const queryClient = useQueryClient();
  const [prefixFilter, setPrefixFilter] = useState("");

  const { data: namespaces = [] } = useQuery({
    queryKey: ["memory-namespaces", prefixFilter],
    queryFn: () => adminApi.memoryNamespaces(prefixFilter || undefined),
    refetchInterval: 30000,
  });

  const purgeMutation = useMutation({
    mutationFn: adminApi.purgeNamespace,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["memory-namespaces"] }),
  });

  const grouped = useMemo(() => {
    return namespaces.reduce<Record<string, typeof namespaces>>((acc, namespace) => {
      const group = namespace.prefix || "(none)";
      if (!acc[group]) acc[group] = [];
      acc[group].push(namespace);
      return acc;
    }, {});
  }, [namespaces]);

  return (
    <>
      <PageHeader
        title="Memory Namespaces"
        subtitle="Grouped namespace inventory with explicit purge controls."
        action={
          <input
            value={prefixFilter}
            onChange={(event) => setPrefixFilter(event.target.value)}
            placeholder="Filter prefix"
            className="rounded border border-slate-700 bg-slate-950 px-3 py-1 text-xs"
          />
        }
      />

      <div className="space-y-4">
        {Object.entries(grouped).length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">No namespaces available.</p>
          </Card>
        ) : (
          Object.entries(grouped).map(([prefix, items]) => (
            <Card key={prefix}>
              <p className="text-[10px] uppercase tracking-[0.2em] text-amber-300">{prefix}</p>
              <div className="mt-3 space-y-2">
                {items.map((item) => (
                  <div
                    key={item.namespace}
                    className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-800 bg-slate-950/60 px-3 py-2"
                  >
                    <div>
                      <p className="font-mono text-xs text-slate-200">{item.namespace}</p>
                      <p className="text-[10px] text-slate-500">records={item.records}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm(`Purge namespace '${item.namespace}'?`)) {
                          purgeMutation.mutate(item.namespace);
                        }
                      }}
                      className="rounded border border-rose-700 bg-rose-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-rose-300"
                    >
                      Purge
                    </button>
                  </div>
                ))}
              </div>
            </Card>
          ))
        )}
      </div>
    </>
  );
}
