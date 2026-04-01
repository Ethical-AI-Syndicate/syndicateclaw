import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminApi } from "@/api/client";
import { Card, PageHeader } from "@/components/Layout";

export default function AuditLog() {
  const [actorFilter, setActorFilter] = useState("");
  const [domainFilter, setDomainFilter] = useState("");

  const { data: events = [] } = useQuery({
    queryKey: ["audit-events", actorFilter, domainFilter],
    queryFn: () =>
      adminApi.auditEvents({
        limit: 200,
        actor: actorFilter || undefined,
        domain: domainFilter || undefined,
      }),
    refetchInterval: 30000,
  });

  return (
    <>
      <PageHeader
        title="Audit Log"
        subtitle="Filtered event stream by actor/domain with compact table density."
        action={
          <div className="flex gap-2">
            <input
              value={actorFilter}
              onChange={(event) => setActorFilter(event.target.value)}
              placeholder="Actor"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
            />
            <input
              value={domainFilter}
              onChange={(event) => setDomainFilter(event.target.value)}
              placeholder="Domain"
              className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
            />
          </div>
        }
      />

      <Card className="overflow-x-auto p-0">
        <table className="min-w-full text-[10px]">
          <thead className="border-b border-slate-800 bg-slate-950/70 uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th className="px-2 py-2 text-left">Time</th>
              <th className="px-2 py-2 text-left">Actor</th>
              <th className="px-2 py-2 text-left">Domain</th>
              <th className="px-2 py-2 text-left">Effect</th>
              <th className="px-2 py-2 text-left">Action</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                  No audit entries found.
                </td>
              </tr>
            ) : (
              events.map((event) => (
                <tr key={event.id} className="border-b border-slate-900/80 hover:bg-slate-950/50">
                  <td className="px-2 py-1 text-slate-500">{new Date(event.at).toLocaleString()}</td>
                  <td className="px-2 py-1 text-slate-300">{event.actor}</td>
                  <td className="px-2 py-1 text-slate-300">{event.domain}</td>
                  <td className="px-2 py-1 text-amber-300">{event.effect}</td>
                  <td className="px-2 py-1 text-slate-400">{event.action}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </>
  );
}
