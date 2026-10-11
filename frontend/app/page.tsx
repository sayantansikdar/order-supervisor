"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Run, Supervisor, statusColor } from "../lib/api";

export default function Dashboard() {
  const router = useRouter();
  const [supervisors, setSupervisors] = useState<Supervisor[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [supId, setSupId] = useState("");
  const [orderId, setOrderId] = useState("");
  const [instructions, setInstructions] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      const [s, r] = await Promise.all([api.listSupervisors(), api.listRuns()]);
      setSupervisors(s);
      setRuns(r);
      if (!supId && s.length) setSupId(s[0].id);
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, []); // eslint-disable-line

  async function createRun(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const run = await api.createRun({
        supervisor_id: supId,
        order_id: orderId || `ORD-${Math.floor(Math.random() * 9000 + 1000)}`,
        order_context: { source: "ui" },
        instructions: instructions
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setOrderId("");
      setInstructions("");
      await refresh();
      router.push(`/run?id=${run.id}`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold">Start an order run</h2>
        <form onSubmit={createRun} className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Supervisor</span>
            <select
              className="w-full rounded-lg border px-3 py-2"
              value={supId}
              onChange={(e) => setSupId(e.target.value)}
            >
              {supervisors.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} · {s.wake_aggressiveness} · {s.default_wake_seconds}s
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Order ID</span>
            <input
              className="w-full rounded-lg border px-3 py-2"
              placeholder="auto-generated if blank"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
            />
          </label>
          <label className="block text-sm md:col-span-2">
            <span className="mb-1 block font-medium text-slate-600">
              Run-specific instructions (one per line, optional)
            </span>
            <textarea
              className="h-20 w-full rounded-lg border px-3 py-2"
              placeholder={"If shipment is delayed, escalate immediately.\nDo not contact the customer without human review."}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
            />
          </label>
          <div className="md:col-span-2">
            <button
              disabled={creating || !supId}
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {creating ? "Starting…" : "Start run"}
            </button>
          </div>
        </form>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
      </section>

      <section>
        <h2 className="mb-4 text-lg font-semibold">Runs</h2>
        <div className="grid gap-3">
          {runs.length === 0 && (
            <p className="text-sm text-slate-500">No runs yet — start one above.</p>
          )}
          {runs.map((r) => (
            <Link
              key={r.id}
              href={`/run?id=${r.id}`}
              className="flex items-center justify-between rounded-lg border bg-white px-4 py-3 shadow-sm hover:border-slate-400"
            >
              <div>
                <div className="font-medium">{r.order_id}</div>
                <div className="text-xs text-slate-500">
                  {r.turns} turns · {r.sleep_state}
                  {r.next_wake_at
                    ? ` · next wake ${new Date(r.next_wake_at).toLocaleTimeString()}`
                    : ""}
                </div>
              </div>
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${statusColor(r.status)}`}>
                {r.status}
              </span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
