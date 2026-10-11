"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  api,
  DEMO,
  EVENT_TYPES,
  RunDetail,
  kindColor,
  statusColor,
} from "../../lib/api";
import { demoApi } from "../../lib/demo";

const TERMINAL = ["completed", "terminated", "failed"];

export default function RunPage() {
  return (
    <Suspense fallback={<p className="text-sm text-slate-500">Loading run…</p>}>
      <RunView />
    </Suspense>
  );
}

function RunView() {
  const runId = useSearchParams().get("id") || "";
  const [run, setRun] = useState<RunDetail | null>(null);
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setRun(await api.getRun(runId));
    } catch (e: any) {
      setError(e.message);
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [runId]); // eslint-disable-line

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!run) return <p className="text-sm text-slate-500">Loading run…</p>;

  const terminal = TERMINAL.includes(run.status);
  const timeline = [...run.timeline].reverse();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Link href="/" className="text-sm text-slate-500 hover:underline">
            ← all runs
          </Link>
          <h1 className="text-2xl font-bold">{run.order_id}</h1>
          <p className="text-sm text-slate-500">
            {run.supervisor?.name} · workflow {run.workflow_id}
          </p>
        </div>
        <span className={`rounded-full px-4 py-1.5 text-sm font-semibold ${statusColor(run.status)}`}>
          {run.status}
        </span>
      </div>

      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        {/* -------- Left: state + controls -------- */}
        <div className="space-y-4">
          <Card title="State">
            <Row label="Sleep">{run.sleep_state}</Row>
            <Row label="Turns">{run.turns}</Row>
            <Row label="Next wake">
              {run.next_wake_at ? new Date(run.next_wake_at).toLocaleTimeString() : "—"}
            </Row>
            <Row label="Aggressiveness">{run.supervisor?.wake_aggressiveness}</Row>
          </Card>

          <Card title="Memory summary">
            <pre className="whitespace-pre-wrap text-xs text-slate-600">
              {run.memory_summary || "(empty)"}
            </pre>
            {run.wake_guidance && (
              <p className="mt-2 border-t pt-2 text-[11px] text-slate-400">
                Wake guidance: {run.wake_guidance}
              </p>
            )}
          </Card>

          <Card title="Controls">
            <div className="flex flex-wrap gap-2">
              <button
                disabled={busy || terminal}
                onClick={() => act(() => api.control(run.id, "interrupt"))}
                className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Pause
              </button>
              <button
                disabled={busy || terminal}
                onClick={() => act(() => api.control(run.id, "resume"))}
                className="rounded-lg border px-3 py-1.5 text-sm disabled:opacity-40"
              >
                Resume
              </button>
              {DEMO && (
                <button
                  disabled={busy || terminal || run.sleep_state !== "sleeping"}
                  onClick={() => act(() => demoApi.fastForward(run.id))}
                  title="Demo only: skip the durable timer and wake the agent now"
                  className="rounded-lg border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-sm text-indigo-700 disabled:opacity-40"
                >
                  ⏩ Next wake-up
                </button>
              )}
              <button
                disabled={busy || terminal}
                onClick={() => act(() => api.control(run.id, "terminate"))}
                className="rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-600 disabled:opacity-40"
              >
                Terminate
              </button>
            </div>
          </Card>

          <Card title="Inject event">
            <div className="flex flex-wrap gap-2">
              {EVENT_TYPES.map((t) => (
                <button
                  key={t}
                  disabled={busy || terminal}
                  onClick={() => act(() => api.sendEvent(run.id, t))}
                  className="rounded-full border border-sky-300 bg-sky-50 px-3 py-1 text-xs text-sky-700 disabled:opacity-40"
                >
                  {t}
                </button>
              ))}
            </div>
          </Card>

          <Card title="Add instruction to this run">
            <textarea
              className="h-16 w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="e.g. Prioritize speed over cost for this order."
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
            />
            <button
              disabled={busy || terminal || !instruction.trim()}
              onClick={() =>
                act(async () => {
                  await api.addInstruction(run.id, instruction.trim());
                  setInstruction("");
                })
              }
              className="mt-2 rounded-lg bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
            >
              Add instruction
            </button>
            {run.extra_instructions.length > 0 && (
              <ul className="mt-3 space-y-1 border-t pt-2 text-xs text-slate-600">
                {run.extra_instructions.map((i, idx) => (
                  <li key={idx}>• {i}</li>
                ))}
              </ul>
            )}
          </Card>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>

        {/* -------- Right: timeline + final -------- */}
        <div className="space-y-4">
          {run.final_output && (
            <div className="rounded-xl border border-green-500 bg-green-50 p-5">
              <h3 className="mb-2 font-semibold text-green-800">Final summary</h3>
              <p className="text-sm text-slate-700">{run.final_output.final_summary}</p>
              <FinalList title="Important actions" items={run.final_output.important_actions} />
              <FinalList title="Key learnings" items={run.final_output.key_learnings} />
              <FinalList title="Feedback" items={run.final_output.feedback} />
            </div>
          )}

          <Card title={`Timeline (${run.timeline.length})`}>
            <div className="space-y-2">
              {timeline.map((e) => (
                <div key={e.id} className={`rounded-lg border-l-4 px-3 py-2 ${kindColor(e.kind)}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{e.title}</span>
                    <span className="text-[11px] uppercase tracking-wide text-slate-400">
                      {e.kind}
                      {e.importance === "high" ? " · !" : ""}
                    </span>
                  </div>
                  {e.detail && <p className="mt-0.5 text-xs text-slate-600">{e.detail}</p>}
                  <div className="mt-0.5 text-[10px] text-slate-400">
                    {new Date(e.created_at).toLocaleTimeString()}
                    {e.trigger ? ` · ${e.trigger}` : ""}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-semibold text-slate-700">{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b py-1 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium">{children}</span>
    </div>
  );
}

function FinalList({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mt-3">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-green-700">{title}</h4>
      <ul className="mt-1 space-y-0.5 text-sm text-slate-700">
        {items.map((it, i) => (
          <li key={i}>• {it}</li>
        ))}
      </ul>
    </div>
  );
}
