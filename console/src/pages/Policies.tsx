import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { policiesApi, type PolicyRule } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

type SortMode = "priority-desc" | "priority-asc";

export default function Policies() {
  const queryClient = useQueryClient();
  const [sortMode, setSortMode] = useState<SortMode>("priority-desc");
  const [form, setForm] = useState({
    name: "",
    resource_type: "workflow",
    resource_pattern: "*",
    effect: "allow",
    priority: 100,
    description: "",
  });

  const { data: rules = [] } = useQuery({
    queryKey: ["policies"],
    queryFn: policiesApi.list,
  });

  const createMutation = useMutation({
    mutationFn: policiesApi.create,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["policies"] });
      setForm({
        name: "",
        resource_type: "workflow",
        resource_pattern: "*",
        effect: "allow",
        priority: 100,
        description: "",
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Parameters<typeof policiesApi.update>[1] }) =>
      policiesApi.update(id, patch),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: policiesApi.delete,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });

  const sortedRules = useMemo(() => {
    const items = [...rules];
    items.sort((a, b) => {
      if (sortMode === "priority-asc") return a.priority - b.priority;
      return b.priority - a.priority;
    });
    return items;
  }, [rules, sortMode]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    createMutation.mutate({
      name: form.name,
      description: form.description,
      resource_type: form.resource_type,
      resource_pattern: form.resource_pattern,
      effect: form.effect,
      priority: Number(form.priority),
      conditions: [],
    });
  }

  return (
    <>
      <PageHeader
        title="Policies"
        subtitle="Manage rule priority, effect, and enablement across resources."
        action={
          <select
            value={sortMode}
            onChange={(event) => setSortMode(event.target.value as SortMode)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          >
            <option value="priority-desc">Priority ↓</option>
            <option value="priority-asc">Priority ↑</option>
          </select>
        }
      />

      <Card>
        <form className="grid gap-2 md:grid-cols-6" onSubmit={onCreate}>
          <input
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
            placeholder="Rule name"
            required
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          />
          <input
            value={form.resource_type}
            onChange={(event) => setForm((prev) => ({ ...prev, resource_type: event.target.value }))}
            placeholder="Resource type"
            required
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          />
          <input
            value={form.resource_pattern}
            onChange={(event) => setForm((prev) => ({ ...prev, resource_pattern: event.target.value }))}
            placeholder="Pattern"
            required
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          />
          <select
            value={form.effect}
            onChange={(event) => setForm((prev) => ({ ...prev, effect: event.target.value }))}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          >
            <option value="allow">allow</option>
            <option value="deny">deny</option>
          </select>
          <input
            value={form.priority}
            type="number"
            onChange={(event) => setForm((prev) => ({ ...prev, priority: Number(event.target.value) }))}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
          />
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded border border-amber-700 bg-amber-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-300"
          >
            Add Rule
          </button>
          <input
            value={form.description}
            onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
            placeholder="Description"
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs md:col-span-6"
          />
        </form>
      </Card>

      <div className="mt-3 space-y-2">
        {sortedRules.map((rule: PolicyRule) => (
          <Card key={rule.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-xs font-semibold text-amber-300">{rule.name}</p>
                <p className="text-[10px] text-slate-500">
                  {rule.resource_type}:{rule.resource_pattern} • priority {rule.priority}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={String(rule.effect).toLowerCase() === "allow" ? "success" : "danger"}>
                  {rule.effect}
                </Badge>
                <Badge variant={rule.enabled ? "info" : "warning"}>{rule.enabled ? "enabled" : "disabled"}</Badge>
              </div>
            </div>

            {rule.description ? <p className="mt-2 text-xs text-slate-400">{rule.description}</p> : null}

            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() =>
                  updateMutation.mutate({
                    id: rule.id,
                    patch: { enabled: !rule.enabled },
                  })
                }
                className="rounded border border-cyan-700 bg-cyan-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-cyan-300"
              >
                Toggle Enable
              </button>
              <button
                type="button"
                onClick={() => deleteMutation.mutate(rule.id)}
                className="rounded border border-rose-700 bg-rose-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-rose-300"
              >
                Disable Rule
              </button>
            </div>
          </Card>
        ))}

        {sortedRules.length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">No policy rules available.</p>
          </Card>
        ) : null}
      </div>
    </>
  );
}
