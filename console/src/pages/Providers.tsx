import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { providersApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

export default function Providers() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["providers-list"],
    queryFn: providersApi.list,
  });

  const syncMutation = useMutation({
    mutationFn: providersApi.syncModelsDev,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["providers-list"] });
    },
  });

  const providers = data?.providers ?? [];

  return (
    <>
      <PageHeader
        title="Providers"
        subtitle="Inference provider topology and catalog synchronization controls."
        action={
          <button
            type="button"
            onClick={() => syncMutation.mutate()}
            className="rounded border border-amber-700 bg-amber-900/20 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-300 hover:bg-amber-800/30"
          >
            {syncMutation.isPending ? "Syncing..." : "Sync models.dev"}
          </button>
        }
      />

      {isLoading ? <p className="text-xs text-slate-500">Loading providers...</p> : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {providers.length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">No providers discovered.</p>
          </Card>
        ) : (
          providers.map((provider) => (
            <Card key={provider.id}>
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-amber-300">{provider.name}</p>
                <Badge variant={provider.enabled === false ? "danger" : "success"}>
                  {provider.enabled === false ? "Disabled" : "Enabled"}
                </Badge>
              </div>
              <p className="mt-2 text-[10px] text-slate-500">ID: {provider.id}</p>
              <p className="mt-1 text-[10px] text-slate-500">Adapter: {provider.adapter_protocol}</p>
              <p className="mt-3 text-[10px] text-slate-500">Allowed models</p>
              <p className="text-xs text-slate-300">{provider.allowed_models?.length ?? 0}</p>
            </Card>
          ))
        )}
      </div>
    </>
  );
}
