import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

export default function ApiKeys() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [rawKey, setRawKey] = useState<string | null>(null);

  const { data: keys = [] } = useQuery({
    queryKey: ["api-keys"],
    queryFn: adminApi.listApiKeys,
  });

  const createMutation = useMutation({
    mutationFn: adminApi.createApiKey,
    onSuccess: (response) => {
      setRawKey(response.key);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: adminApi.revokeApiKey,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  function onCreate(event: FormEvent) {
    event.preventDefault();
    createMutation.mutate({ name });
  }

  return (
    <>
      <PageHeader title="API Keys" subtitle="Issue, reveal-once, and revoke API credentials." />

      {rawKey ? (
        <Card className="mb-3 border-amber-700 bg-amber-900/20">
          <p className="text-[10px] uppercase tracking-[0.2em] text-amber-300">New key (copy now)</p>
          <p className="mt-2 break-all font-mono text-xs text-amber-100">{rawKey}</p>
          <button
            type="button"
            onClick={() => navigator.clipboard.writeText(rawKey)}
            className="mt-3 rounded border border-amber-600 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-300"
          >
            Copy key
          </button>
        </Card>
      ) : null}

      <Card>
        <form onSubmit={onCreate} className="flex flex-wrap items-center gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Key name"
            required
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          />
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded border border-amber-700 bg-amber-900/20 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-300"
          >
            Create API Key
          </button>
        </form>
      </Card>

      <div className="mt-3 space-y-2">
        {keys.length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">No API keys to display.</p>
          </Card>
        ) : (
          keys.map((key) => (
            <Card key={key.key_id}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold text-amber-300">{key.name}</p>
                  <p className="mt-1 font-mono text-[10px] text-slate-500">{key.prefix}</p>
                </div>
                <Badge variant={key.revoked ? "danger" : "success"}>{key.revoked ? "revoked" : "active"}</Badge>
              </div>
              <p className="mt-2 text-[10px] text-slate-500">Created {new Date(key.created_at).toLocaleString()}</p>
              <button
                type="button"
                onClick={() => revokeMutation.mutate(key.key_id)}
                className="mt-3 rounded border border-rose-700 bg-rose-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-rose-300"
              >
                Revoke
              </button>
            </Card>
          ))
        )}
      </div>
    </>
  );
}
