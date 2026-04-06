import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminApi } from "@/api/client";
import { Badge, Card, PageHeader } from "@/components/Layout";

type PlatformKey = "telegram" | "discord" | "slack";

const envReferences: Record<PlatformKey, string[]> = {
  telegram: [
    "SYNDICATECLAW_PUBLIC_BASE_URL",
    "SYNDICATECLAW_TELEGRAM_BOT_TOKEN",
    "SYNDICATECLAW_TELEGRAM_WEBHOOK_SECRET",
  ],
  discord: [
    "SYNDICATECLAW_DISCORD_BOT_TOKEN",
    "SYNDICATECLAW_DISCORD_APP_ID",
    "SYNDICATECLAW_DISCORD_PUBLIC_KEY",
    "SYNDICATECLAW_DISCORD_GUILD_IDS",
  ],
  slack: [
    "SYNDICATECLAW_SLACK_BOT_TOKEN",
    "SYNDICATECLAW_SLACK_SIGNING_SECRET",
  ],
};

const setupSteps: Record<PlatformKey, string[]> = {
  telegram: [
    "Create a Telegram bot via BotFather and copy token.",
    "Set public HTTPS URL reachable by Telegram.",
    "Configure webhook secret and restart API service.",
  ],
  discord: [
    "Create app and bot in Discord developer portal.",
    "Set interaction endpoint to /webhooks/discord/interactions.",
    "Provide app ID/public key and optional guild IDs.",
  ],
  slack: [
    "Create Slack app and install bot token scopes.",
    "Set signing secret and event request URL.",
    "Configure slash command URL /webhooks/slack/command.",
  ],
};

export default function ConsoleSettings() {
  const [open, setOpen] = useState<PlatformKey | null>("telegram");
  const { data: connectors = [] } = useQuery({
    queryKey: ["settings-connectors"],
    queryFn: adminApi.connectors,
    refetchInterval: 20000,
  });

  const statusMap = useMemo(() => {
    const map: Record<string, boolean> = {};
    connectors.forEach((item) => {
      map[item.platform.toLowerCase()] = item.connected;
    });
    return map;
  }, [connectors]);

  const envSnippet = [
    "SYNDICATECLAW_PUBLIC_BASE_URL=https://your-domain.tld",
    "SYNDICATECLAW_TELEGRAM_BOT_TOKEN=...",
    "SYNDICATECLAW_TELEGRAM_WEBHOOK_SECRET=...",
    "SYNDICATECLAW_DISCORD_BOT_TOKEN=...",
    "SYNDICATECLAW_DISCORD_APP_ID=...",
    "SYNDICATECLAW_DISCORD_PUBLIC_KEY=...",
    "SYNDICATECLAW_DISCORD_GUILD_IDS=",
    "SYNDICATECLAW_SLACK_BOT_TOKEN=...",
    "SYNDICATECLAW_SLACK_SIGNING_SECRET=...",
    "SYNDICATECLAW_CONSOLE_ENABLED=true",
  ].join("\n");

  return (
    <>
      <PageHeader
        title="Console Settings"
        subtitle="Connector setup playbooks, env var references, and copy-ready snippets."
      />

      <div className="space-y-3">
        {(["telegram", "discord", "slack"] as PlatformKey[]).map((platform) => {
          const expanded = open === platform;
          const isConnected = statusMap[platform] ?? false;
          return (
            <Card key={platform}>
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : platform)}
                className="flex w-full items-center justify-between"
              >
                <p className="text-xs font-semibold uppercase tracking-wider text-amber-300">{platform}</p>
                <Badge variant={isConnected ? "success" : "warning"}>
                  {isConnected ? "Connected" : "Not Connected"}
                </Badge>
              </button>

              {expanded ? (
                <div className="mt-4 space-y-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Setup steps</p>
                    <ol className="mt-2 space-y-1 text-xs text-slate-300">
                      {setupSteps[platform].map((step, index) => (
                        <li key={step}>{index + 1}. {step}</li>
                      ))}
                    </ol>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">Environment vars</p>
                    <div className="mt-2 space-y-1">
                      {envReferences[platform].map((envVar) => (
                        <div key={envVar} className="flex items-center justify-between rounded border border-slate-800 bg-slate-950/70 px-2 py-1">
                          <code className="text-[10px] text-slate-300">{envVar}</code>
                          <button
                            type="button"
                            onClick={() => navigator.clipboard.writeText(envVar)}
                            className="text-[10px] uppercase tracking-[0.2em] text-amber-400"
                          >
                            Copy
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </Card>
          );
        })}
      </div>

      <Card className="mt-4">
        <p className="text-[10px] uppercase tracking-[0.2em] text-slate-500">.env snippet</p>
        <pre className="mt-3 overflow-x-auto rounded border border-slate-800 bg-slate-950/70 p-3 text-[10px] text-slate-300">
          {envSnippet}
        </pre>
        <button
          type="button"
          onClick={() => navigator.clipboard.writeText(envSnippet)}
          className="mt-2 rounded border border-amber-700 bg-amber-900/20 px-2 py-1 text-[10px] uppercase tracking-[0.2em] text-amber-300"
        >
          Copy all
        </button>
      </Card>
    </>
  );
}
