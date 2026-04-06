import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { adminApi } from "@/api/client";

export default function Login() {
  const navigate = useNavigate();
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    localStorage.setItem("sc_api_key", apiKey.trim());
    try {
      await adminApi.dashboard();
      navigate("/console", { replace: true });
    } catch {
      localStorage.removeItem("sc_api_key");
      setError("Invalid API key or admin endpoint unavailable.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-slate-950 text-slate-200">
      <div className="absolute inset-0 bg-[linear-gradient(rgba(245,158,11,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(245,158,11,0.08)_1px,transparent_1px)] bg-[size:24px_24px]" />
      <div className="relative mx-auto flex min-h-screen max-w-lg items-center px-6">
        <form
          onSubmit={onSubmit}
          className="w-full rounded border border-slate-700 bg-slate-900/90 p-6 shadow-2xl shadow-black/30"
        >
          <p className="text-[10px] uppercase tracking-[0.3em] text-slate-500">SyndicateClaw</p>
          <h1 className="mt-2 text-xl font-bold text-amber-400">Console Access</h1>
          <p className="mt-2 text-xs text-slate-400">
            Enter an API key with permissions to read `/api/v1/admin/*`.
          </p>

          <label className="mt-6 block text-[10px] uppercase tracking-[0.25em] text-slate-500">API Key</label>
          <input
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            type="password"
            placeholder="sc_live_..."
            required
            className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 outline-none ring-amber-500/40 placeholder:text-slate-600 focus:ring"
          />

          {error ? <p className="mt-3 text-xs text-rose-300">{error}</p> : null}

          <button
            type="submit"
            disabled={loading || !apiKey.trim()}
            className="mt-6 w-full rounded border border-amber-700 bg-amber-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.2em] text-amber-300 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Verifying..." : "Enter Console"}
          </button>
        </form>
      </div>
    </div>
  );
}
