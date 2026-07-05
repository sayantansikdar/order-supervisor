"use client";

import { useEffect, useState } from "react";
import { api, Supervisor } from "../../lib/api";

export default function SupervisorsPage() {
  const [supervisors, setSupervisors] = useState<Supervisor[]>([]);
  const [tools, setTools] = useState<{ name: string; description: string }[]>([]);
  const [form, setForm] = useState({
    name: "",
    base_instruction: "",
    default_wake_seconds: 90,
    wake_aggressiveness: "medium",
    tools: [] as string[],
  });
  const [error, setError] = useState("");

  async function refresh() {
    const [s, t] = await Promise.all([api.listSupervisors(), api.listTools()]);
    setSupervisors(s);
    setTools(t);
    if (form.tools.length === 0) setForm((f) => ({ ...f, tools: t.map((x) => x.name) }));
  }

  useEffect(() => {
    refresh();
  }, []); // eslint-disable-line

  function toggleTool(name: string) {
    setForm((f) => ({
      ...f,
      tools: f.tools.includes(name)
        ? f.tools.filter((n) => n !== name)
        : [...f.tools, name],
    }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createSupervisor(form);
      setForm({ ...form, name: "", base_instruction: "" });
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  }

  return (
    <div className="grid gap-8 md:grid-cols-2">
      <section>
        <h2 className="mb-4 text-lg font-semibold">Supervisor templates</h2>
        <div className="grid gap-3">
          {supervisors.map((s) => (
            <div key={s.id} className="rounded-lg border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="font-medium">{s.name}</div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs">
                  {s.wake_aggressiveness}
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-600">{s.base_instruction}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {s.tools.map((t) => (
                  <span key={t} className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                    {t}
                  </span>
                ))}
              </div>
              <div className="mt-2 text-xs text-slate-400">
                default wake {s.default_wake_seconds}s
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-lg font-semibold">New supervisor</h2>
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Name</span>
            <input
              className="w-full rounded-lg border px-3 py-2"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-600">Base instruction</span>
            <textarea
              className="h-24 w-full rounded-lg border px-3 py-2"
              value={form.base_instruction}
              onChange={(e) => setForm({ ...form, base_instruction: e.target.value })}
              required
            />
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-600">Default wake (s)</span>
              <input
                type="number"
                className="w-full rounded-lg border px-3 py-2"
                value={form.default_wake_seconds}
                onChange={(e) =>
                  setForm({ ...form, default_wake_seconds: Number(e.target.value) })
                }
              />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium text-slate-600">Wake aggressiveness</span>
              <select
                className="w-full rounded-lg border px-3 py-2"
                value={form.wake_aggressiveness}
                onChange={(e) => setForm({ ...form, wake_aggressiveness: e.target.value })}
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
          </div>
          <div className="text-sm">
            <span className="mb-1 block font-medium text-slate-600">Available tools</span>
            <div className="flex flex-wrap gap-2">
              {tools.map((t) => (
                <button
                  type="button"
                  key={t.name}
                  onClick={() => toggleTool(t.name)}
                  title={t.description}
                  className={`rounded-full border px-3 py-1 text-xs ${
                    form.tools.includes(t.name)
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-300 text-slate-600"
                  }`}
                >
                  {t.name}
                </button>
              ))}
            </div>
          </div>
          <button className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white">
            Create supervisor
          </button>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </form>
      </section>
    </div>
  );
}
