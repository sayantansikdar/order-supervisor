export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export type Supervisor = {
  id: string;
  name: string;
  base_instruction: string;
  tools: string[];
  default_wake_seconds: number;
  model: string;
  wake_aggressiveness: string;
  created_at: string;
};

export type TimelineEntry = {
  id: string;
  kind: string;
  title: string;
  detail: string;
  data?: Record<string, unknown> | null;
  importance: string;
  trigger?: string | null;
  created_at: string;
};

export type Run = {
  id: string;
  supervisor_id: string;
  order_id: string;
  order_context: Record<string, unknown>;
  status: string;
  sleep_state: string;
  workflow_id?: string | null;
  memory_summary: string;
  wake_guidance: string;
  extra_instructions: string[];
  next_wake_at?: string | null;
  turns: number;
  final_output?: FinalOutput | null;
  created_at: string;
  updated_at: string;
};

export type FinalOutput = {
  final_summary?: string;
  important_actions?: string[];
  key_learnings?: string[];
  feedback?: string[];
  closed_reason?: string;
};

export type RunDetail = Run & {
  timeline: TimelineEntry[];
  supervisor?: Supervisor | null;
};

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  listSupervisors: () =>
    fetch(`${API_BASE}/api/supervisors`, { cache: "no-store" }).then(j<Supervisor[]>),
  createSupervisor: (body: Partial<Supervisor>) =>
    fetch(`${API_BASE}/api/supervisors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<Supervisor>),
  listTools: () =>
    fetch(`${API_BASE}/api/supervisors/tools`, { cache: "no-store" }).then(
      j<{ name: string; description: string; control: boolean }[]>
    ),

  listRuns: () => fetch(`${API_BASE}/api/runs`, { cache: "no-store" }).then(j<Run[]>),
  getRun: (id: string) =>
    fetch(`${API_BASE}/api/runs/${id}`, { cache: "no-store" }).then(j<RunDetail>),
  createRun: (body: {
    supervisor_id: string;
    order_id: string;
    order_context?: Record<string, unknown>;
    instructions?: string[];
  }) =>
    fetch(`${API_BASE}/api/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(j<Run>),
  sendEvent: (id: string, type: string, payload: Record<string, unknown> = {}) =>
    fetch(`${API_BASE}/api/runs/${id}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, payload }),
    }).then(j<Run>),
  addInstruction: (id: string, text: string) =>
    fetch(`${API_BASE}/api/runs/${id}/instructions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).then(j<Run>),
  control: (id: string, action: "interrupt" | "resume" | "terminate") =>
    fetch(`${API_BASE}/api/runs/${id}/${action}`, { method: "POST" }).then(j<Run>),
};

export const EVENT_TYPES = [
  "payment_confirmed",
  "payment_failed",
  "shipment_created",
  "shipment_delayed",
  "delivered",
  "refund_requested",
  "customer_message_received",
  "no_update_for_n_hours",
  "mystery_event",
];

export function statusColor(status: string): string {
  switch (status) {
    case "sleeping":
      return "bg-indigo-100 text-indigo-700";
    case "active":
      return "bg-emerald-100 text-emerald-700";
    case "review":
      return "bg-amber-100 text-amber-700";
    case "paused":
      return "bg-slate-200 text-slate-700";
    case "completed":
      return "bg-green-600 text-white";
    case "terminated":
      return "bg-red-600 text-white";
    case "failed":
      return "bg-red-200 text-red-800";
    default:
      return "bg-slate-100 text-slate-600";
  }
}

export function kindColor(kind: string): string {
  switch (kind) {
    case "event":
      return "border-sky-400 bg-sky-50";
    case "action":
      return "border-emerald-400 bg-emerald-50";
    case "agent":
      return "border-violet-400 bg-violet-50";
    case "observation":
      return "border-amber-400 bg-amber-50";
    case "final":
      return "border-green-500 bg-green-50";
    default:
      return "border-slate-300 bg-slate-50";
  }
}
