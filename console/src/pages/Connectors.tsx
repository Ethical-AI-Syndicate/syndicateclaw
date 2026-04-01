import { useQuery } from "@tanstack/react-query";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

const platformEmoji: Record<string, string> = {
  telegram: "✈️",
  discord: "🎮",
  slack: "💬",
};

export default function Connectors() {
  const { data: connectors = [] } = useQuery({
    queryKey: ["connectors"],
    queryFn: adminApi.connectors,
    refetchInterval: 20000,
  });

  return (
    <>
      <PageHeader
        title="Connectors"
        subtitle="Live connector health, event throughput, and error counters."
      />

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {connectors.length === 0 ? (
          <Card>
            <p className="text-xs text-slate-500">No connector status available.</p>
          </Card>
        ) : (
          connectors.map((item) => (
            <Card key={item.platform}>
              <div className="flex items-center justify-between">
                <p className="text-lg">{platformEmoji[item.platform] ?? "🔌"}</p>
                <Badge variant={item.connected ? "success" : "danger"}>
                  {item.connected ? "Connected" : "Disconnected"}
                </Badge>
              </div>
              <p className="mt-2 text-xs font-semibold uppercase tracking-wider text-amber-300">
                {item.platform}
              </p>
              <p className="mt-3 text-[10px] text-slate-500">Events received</p>
              <p className="text-lg text-slate-200">{item.events_received}</p>
              <p className="mt-2 text-[10px] text-slate-500">Errors</p>
              <p className="text-lg text-rose-300">{item.errors}</p>
              {item.detail ? <p className="mt-3 text-[10px] text-slate-500">{item.detail}</p> : null}
            </Card>
          ))
        )}
      </div>
    </>
  );
}
