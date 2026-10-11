/**
 * In-browser demo backend.
 *
 * The hosted static build (GitHub Pages) has no FastAPI / Temporal / Postgres,
 * so this module stands in for them. It mirrors the backend 1:1:
 *   - OrderSupervisorWorkflow's loop (signals, durable timer, pause/resume,
 *     terminate, classifier-gated events, instruction wake-ups, finalize)
 *   - the deterministic mock agent policy, wake classifier and finalizer
 *     from backend/app/agent/mock.py
 *   - the mocked tools from backend/app/agent/tools.py
 * State lives in localStorage, so a run survives page reloads — the same
 * "durable" property Temporal gives the real thing.
 */
import type { FinalOutput, Run, RunDetail, Supervisor, TimelineEntry } from "./api";

const KEY = "order-supervisor-demo-v1";
const CONTINUE_AS_NEW_AFTER = 200;
const TERMINAL = new Set(["completed", "terminated", "failed"]);

// ---------------------------------------------------------------- tools
type ToolSpec = { name: string; description: string; control: boolean };
const TOOLS: Record<string, ToolSpec> = {
  send_customer_message: { name: "send_customer_message", description: "Send a message to the customer (email/SMS).", control: false },
  create_internal_note: { name: "create_internal_note", description: "Record an internal note for the ops team.", control: false },
  escalate_issue: { name: "escalate_issue", description: "Escalate the order to a human ops agent.", control: false },
  mark_order_for_review: { name: "mark_order_for_review", description: "Flag the order for manual review.", control: false },
  schedule_next_wake: { name: "schedule_next_wake", description: "Set when the supervisor should wake up next.", control: true },
  close_workflow: { name: "close_workflow", description: "End supervision — the order reached a terminal state.", control: true },
};
const DEFAULT_TOOL_NAMES = Object.keys(TOOLS);

function simulateTool(name: string, args: Record<string, any>): [string, string] {
  switch (name) {
    case "send_customer_message": return ["📧 Sent customer message", args.message ?? "(no content)"];
    case "create_internal_note": return ["📝 Internal note", args.text ?? "(empty)"];
    case "escalate_issue": return ["🚨 Escalated to human ops", args.reason ?? "(no reason)"];
    case "mark_order_for_review": return ["🔎 Marked order for review", args.reason ?? "(no reason)"];
    case "schedule_next_wake": return ["⏰ Scheduled next wake-up", `in ${args.seconds ?? "?"}s`];
    case "close_workflow": return ["✅ Closing supervision", args.reason ?? "(terminal state reached)"];
    default: return [`🔧 ${name}`, JSON.stringify(args)];
  }
}

// ---------------------------------------------------------------- state
type Ctl = {
  events: Record<string, any>[];
  newInstruction: boolean;
  paused: boolean;
  terminated: boolean;
  terminateReason: string;
  nextWakeMs: number | null;
  sinceContinue: number;
};
type DemoRun = Run & { _ctl: Ctl };
type DB = { supervisors: Supervisor[]; runs: DemoRun[]; timeline: TimelineEntry[]; clock: number };

const TEMPLATES = [
  {
    name: "Standard Order Supervisor",
    base_instruction:
      "Watch this order end-to-end. Keep the customer informed, resolve payment and shipment problems quickly, escalate anything risky, and close out cleanly on delivery.",
    default_wake_seconds: 90,
    wake_aggressiveness: "medium",
  },
  {
    name: "High-Touch VIP Supervisor",
    base_instruction:
      "This is a VIP order. Be proactive and fast. Prefer over-communication with the customer, escalate delays immediately, and never let an issue sit unattended.",
    default_wake_seconds: 45,
    wake_aggressiveness: "high",
  },
  {
    name: "Hands-Off Compliance Supervisor",
    base_instruction:
      "Supervise conservatively. Do not contact the customer without human review. Prefer internal notes and reviews over direct action.",
    default_wake_seconds: 180,
    wake_aggressiveness: "low",
  },
];

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);

function seed(): DB {
  const now = new Date().toISOString();
  return {
    supervisors: TEMPLATES.map((t) => ({
      id: uid(),
      ...t,
      tools: DEFAULT_TOOL_NAMES,
      model: "deterministic-mock",
      created_at: now,
    })),
    runs: [],
    timeline: [],
    clock: 0,
  };
}

let db: DB | null = null;
function load(): DB {
  if (db) return db;
  try {
    const raw = typeof localStorage !== "undefined" ? localStorage.getItem(KEY) : null;
    db = raw ? (JSON.parse(raw) as DB) : seed();
  } catch {
    db = seed();
  }
  return db!;
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(db)); } catch { /* private mode */ }
}

// Monotonic timestamps so timeline order is stable even within one tick.
function stamp(): string {
  const d = load();
  const t = Math.max(Date.now(), d.clock + 1);
  d.clock = t;
  return new Date(t).toISOString();
}

function addEntry(runId: string, kind: string, title: string, detail = "", importance = "normal",
  trigger: string | null = null, data: Record<string, unknown> | null = null) {
  load().timeline.push({ id: uid(), run_id: runId, kind, title, detail, importance, trigger, data, created_at: stamp() } as TimelineEntry & { run_id: string });
}

const findRun = (id: string) => {
  const r = load().runs.find((x) => x.id === id);
  if (!r) throw new Error("404 run not found");
  return r;
};
const findSup = (id: string) => load().supervisors.find((s) => s.id === id)!;
const strip = (r: DemoRun): Run => { const { _ctl, ...rest } = r; return rest; };

// ---------------------------------------------------------------- agent policy (port of mock.py)
const TERMINAL_EVENTS = new Set(["delivered", "order_cancelled", "refund_completed"]);

function instrFlags(instructions: string[]) {
  const text = instructions.join(" ").toLowerCase();
  return {
    escalate_delays: text.includes("delay") && text.includes("escalat"),
    no_contact: (text.includes("human review") && text.includes("contact")) || text.includes("do not contact") || text.includes("don't contact"),
    speed: text.includes("speed") || text.includes("prioritize speed"),
  };
}

function rollMemory(prev: string, trigger: string, etype: string, reasoning: string) {
  const tag = etype || trigger;
  let lines = prev.split("\n").filter((l) => l.trim());
  lines.push(`[${tag}] ${reasoning}`);
  if (lines.length > 8) lines = [`(+${lines.length - 8} earlier events summarized)`, ...lines.slice(-8)];
  return lines.join("\n");
}

function agentDecision(ctx: { trigger: string; event: Record<string, any> | null; default_wake_seconds: number;
  extra_instructions: string[]; memory_summary: string; order_id: string }) {
  const { trigger } = ctx;
  const etype: string = ctx.event?.type ?? "";
  const def = ctx.default_wake_seconds || 120;
  const flags = instrFlags(ctx.extra_instructions);
  const calls: { tool: string; args: Record<string, any> }[] = [];
  let status = "sleeping";
  let shouldClose = false;
  let nextWake = def;
  let reasoning = "";
  const guidance = "Wake early on payment_failed, shipment_delayed, refund_requested, customer_message_received or unknown events.";
  const note = (text: string) => calls.push({ tool: "create_internal_note", args: { text } });
  const message = (msg: string) =>
    flags.no_contact
      ? calls.push({ tool: "mark_order_for_review", args: { reason: "Customer contact requires human review: " + msg } })
      : calls.push({ tool: "send_customer_message", args: { message: msg } });

  if (trigger === "start") {
    note(`Supervision started for order ${ctx.order_id}. Watching lifecycle.`);
    reasoning = "New order — establishing supervision and a calm watch interval.";
    status = "active";
  } else if (trigger === "instruction") {
    const latest = ctx.extra_instructions[ctx.extra_instructions.length - 1] ?? "(none)";
    note(`Acknowledged new instruction: ${latest}`);
    reasoning = "Absorbed a new run-specific instruction; will apply it going forward.";
    nextWake = Math.max(30, Math.floor(def / 2));
  } else if (etype === "payment_failed") {
    message("We noticed your payment didn't go through. Please retry or update your payment method.");
    calls.push({ tool: "escalate_issue", args: { reason: "Payment failed — revenue at risk." } });
    reasoning = "Payment failed — nudged the customer and escalated for a quick recovery.";
    nextWake = 45;
    status = "review";
  } else if (etype === "refund_requested") {
    calls.push({ tool: "mark_order_for_review", args: { reason: "Refund requested by customer." } });
    note("Refund requested — flagged for review per policy.");
    reasoning = "Refund request needs a human decision; flagged and staying close.";
    nextWake = 60;
    status = "review";
  } else if (etype === "shipment_delayed") {
    message("Your shipment is running late — apologies. We're on it and will keep you posted.");
    if (flags.escalate_delays) {
      calls.push({ tool: "escalate_issue", args: { reason: "Shipment delayed and run instruction demands immediate escalation." } });
      reasoning = "Shipment delayed; run instruction says escalate immediately, so I did.";
    } else {
      note("Shipment delayed — proactively informed customer, monitoring closely.");
      reasoning = "Shipment delayed; reassured the customer and tightened the watch interval.";
    }
    nextWake = flags.speed ? 30 : 45;
  } else if (etype === "customer_message_received") {
    message("Thanks for reaching out — we've got your message and are looking into it right now.");
    reasoning = "Customer reached out; acknowledged quickly to keep them informed.";
    nextWake = 60;
  } else if (etype === "payment_confirmed") {
    note("Payment confirmed. Order funded and healthy.");
    reasoning = "Payment cleared — nothing to do but relax the watch interval.";
    nextWake = Math.max(def, 180);
  } else if (etype === "shipment_created") {
    note("Shipment created and in transit. Tracking.");
    reasoning = "Shipment on its way; calm state, longer sleep.";
    nextWake = Math.max(def, 180);
  } else if (etype === "no_update_for_n_hours") {
    note("No updates for a while — proactively checking order health.");
    reasoning = "Quiet period; did a health check, nothing actionable yet.";
  } else if (TERMINAL_EVENTS.has(etype)) {
    note(`Order reached terminal state via '${etype}'. Wrapping up supervision.`);
    calls.push({ tool: "close_workflow", args: { reason: `Order ${etype}.` } });
    reasoning = "Order is complete — closing the supervision workflow.";
    shouldClose = true;
    status = "active";
  } else if (trigger === "scheduled_wakeup") {
    note("Scheduled review — order steady, no intervention needed.");
    reasoning = "Timer fired; reviewed state and found nothing needing action.";
    nextWake = Math.min(def * 2, 600);
  } else {
    calls.push({ tool: "escalate_issue", args: { reason: `Unknown event '${etype}' — needs human eyes.` } });
    note(`Unrecognized event '${etype}'. Escalated to be safe.`);
    reasoning = "Unfamiliar event; escalated rather than guessing.";
    nextWake = 60;
    status = "review";
  }

  return {
    reasoning,
    tool_calls: calls,
    memory_summary: rollMemory(ctx.memory_summary, trigger, etype, reasoning),
    next_wake_seconds: nextWake,
    status,
    should_close: shouldClose,
    wake_guidance: guidance,
  };
}

function classifyRule(etype: string, aggressiveness: string) {
  const always = new Set(["payment_failed", "refund_requested", "shipment_delayed", "customer_message_received", "delivered", "order_cancelled"]);
  const calm = new Set(["payment_confirmed", "shipment_created", "no_update_for_n_hours"]);
  const known = new Set([...always, ...calm, "order_created"]);
  if (always.has(etype)) return { wake: true, importance: "high", reason: `'${etype}' always warrants immediate attention.` };
  if (!known.has(etype)) return { wake: true, importance: "high", reason: `Unknown event '${etype}' — waking to be safe.` };
  if (aggressiveness === "high") return { wake: true, importance: "normal", reason: "High-aggressiveness policy wakes on every event." };
  if (aggressiveness === "low") return { wake: false, importance: "low", reason: `'${etype}' is routine; staying asleep until scheduled review.` };
  return { wake: false, importance: "low", reason: `'${etype}' is routine; will fold into the next scheduled review.` };
}

// ---------------------------------------------------------------- activities (port of runtime.py)
function runAgent(run: DemoRun, trigger: string, event: Record<string, any> | null) {
  const sup = findSup(run.supervisor_id);
  const decision = agentDecision({
    trigger, event,
    default_wake_seconds: sup.default_wake_seconds,
    extra_instructions: run.extra_instructions,
    memory_summary: run.memory_summary,
    order_id: run.order_id,
  });
  addEntry(run.id, "agent", `Agent woke (${trigger})`, decision.reasoning, "normal", trigger);

  let shouldClose = decision.should_close;
  let nextWake = decision.next_wake_seconds || sup.default_wake_seconds;
  const allowed = new Set(sup.tools?.length ? sup.tools : DEFAULT_TOOL_NAMES);
  for (const call of decision.tool_calls) {
    const spec = TOOLS[call.tool];
    if (!spec) continue;
    if (!allowed.has(call.tool) && !spec.control) continue;
    if (call.tool === "schedule_next_wake") nextWake = Number(call.args.seconds) || nextWake;
    if (call.tool === "close_workflow") shouldClose = true;
    const [title, detail] = simulateTool(call.tool, call.args);
    const importance = call.tool === "escalate_issue" || call.tool === "mark_order_for_review" ? "high" : "normal";
    addEntry(run.id, "action", title, detail, importance, trigger, { tool: call.tool, args: call.args });
  }

  run.memory_summary = decision.memory_summary;
  run.wake_guidance = decision.wake_guidance;
  run.turns += 1;
  run._ctl.sinceContinue += 1;
  nextWake = Math.max(5, Math.min(nextWake, 86400));

  if (shouldClose) {
    run.sleep_state = "awake";
    run.status = "active";
  } else {
    run.status = decision.status === "review" ? "review" : "sleeping";
    run.sleep_state = "sleeping";
    run._ctl.nextWakeMs = Date.now() + nextWake * 1000;
    run.next_wake_at = new Date(run._ctl.nextWakeMs).toISOString();
  }
  run.updated_at = stamp();
  if (shouldClose) finalize(run, "order reached terminal state", "completed");
}

function finalize(run: DemoRun, reason: string, finalStatus: string) {
  run.status = finalStatus;
  run.sleep_state = "awake";
  run.next_wake_at = null;
  run._ctl.nextWakeMs = null;
  const actions = load().timeline
    .filter((e: any) => e.run_id === run.id && e.kind === "action")
    .map((e) => e.title);
  const lastMemory = run.memory_summary ? run.memory_summary.split("\n").slice(-1)[0] : "";
  const output: FinalOutput = {
    final_summary: `Supervised order ${run.order_id} from creation to terminal state '${finalStatus}'. ${lastMemory}`.trim(),
    important_actions: actions.slice(-8).length ? actions.slice(-8) : ["No interventions were required."],
    key_learnings: [
      "Most lifecycle events were routine and safely deferred to scheduled reviews.",
      "Payment and shipment problems were the main triggers for active intervention.",
    ],
    feedback: [
      "Tune wake aggressiveness per merchant risk profile.",
      "Consider auto-drafting customer messages for faster human approval when contact needs review.",
    ],
    closed_reason: reason,
  };
  run.final_output = output;
  addEntry(run.id, "final", "Run closed — final summary generated", output.final_summary ?? "", "high", null, output as any);
  run.updated_at = stamp();
}

// ---------------------------------------------------------------- workflow loop (port of workflows.py)
function step(run: DemoRun) {
  const c = run._ctl;
  if (TERMINAL.has(run.status)) return;
  if (c.terminated) { finalize(run, c.terminateReason, "terminated"); return; }
  if (c.paused) {
    if (run.status !== "paused") { run.status = "paused"; run.sleep_state = "awake"; run.next_wake_at = null; }
    return;
  }
  if (run.status === "paused") {
    // resumed: go back to sleep on the next scheduled timer
    run.status = "sleeping";
    run.sleep_state = "sleeping";
    if (!c.nextWakeMs || c.nextWakeMs < Date.now()) c.nextWakeMs = Date.now() + findSup(run.supervisor_id).default_wake_seconds * 1000;
    run.next_wake_at = new Date(c.nextWakeMs).toISOString();
  }
  const hasWork = c.events.length > 0 || c.newInstruction;
  if (hasWork) {
    while (c.events.length && !TERMINAL.has(run.status)) {
      const event = c.events.shift()!;
      const sup = findSup(run.supervisor_id);
      const d = classifyRule(event.type, sup.wake_aggressiveness);
      addEntry(run.id, "observation", `Classifier: ${d.wake ? "WAKE" : "defer"} — ${event.type}`, d.reason, d.importance, "event", { event, decision: d });
      if (d.wake) runAgent(run, "event", event);
    }
    if (c.newInstruction && !TERMINAL.has(run.status)) {
      c.newInstruction = false;
      runAgent(run, "instruction", null);
    }
  } else if (c.nextWakeMs && Date.now() >= c.nextWakeMs) {
    runAgent(run, "scheduled_wakeup", null);
  }
  if (c.sinceContinue >= CONTINUE_AS_NEW_AFTER && !TERMINAL.has(run.status)) {
    c.sinceContinue = 0;
    addEntry(run.id, "system", "continue_as_new", `History bounded after ${CONTINUE_AS_NEW_AFTER} turns; workflow continued as new.`);
  }
}

function tick() {
  const d = load();
  for (const r of d.runs) step(r);
  save();
}

// The "worker": a durable timer loop. In the real system Temporal owns this.
if (typeof window !== "undefined") {
  setInterval(tick, 1000);
  window.addEventListener("storage", (e) => { if (e.key === KEY) db = null; });
}

const respond = <T,>(v: T) => new Promise<T>((res) => setTimeout(() => res(JSON.parse(JSON.stringify(v))), 120));

// ---------------------------------------------------------------- API (same surface as lib/api.ts)
export const demoApi = {
  listSupervisors: () => respond(load().supervisors),
  createSupervisor: (body: Partial<Supervisor>) => {
    const s: Supervisor = {
      id: uid(),
      name: body.name || "Untitled supervisor",
      base_instruction: body.base_instruction || "",
      tools: body.tools?.length ? body.tools : DEFAULT_TOOL_NAMES,
      default_wake_seconds: Number(body.default_wake_seconds) || 120,
      model: "deterministic-mock",
      wake_aggressiveness: body.wake_aggressiveness || "medium",
      created_at: new Date().toISOString(),
    };
    load().supervisors.push(s);
    save();
    return respond(s);
  },
  listTools: () => respond(Object.values(TOOLS)),

  listRuns: () => {
    tick();
    return respond([...load().runs].sort((a, b) => b.created_at.localeCompare(a.created_at)).map(strip));
  },
  getRun: (id: string) => {
    tick();
    const run = findRun(id);
    const detail: RunDetail = {
      ...strip(run),
      timeline: load().timeline.filter((e: any) => e.run_id === id),
      supervisor: findSup(run.supervisor_id),
    };
    return respond(detail);
  },
  createRun: (body: { supervisor_id: string; order_id: string; order_context?: Record<string, unknown>; instructions?: string[] }) => {
    const sup = findSup(body.supervisor_id);
    if (!sup) throw new Error("404 supervisor not found");
    const id = uid();
    const now = stamp();
    const run: DemoRun = {
      id,
      supervisor_id: sup.id,
      order_id: body.order_id,
      order_context: body.order_context || {},
      status: "created",
      sleep_state: "awake",
      workflow_id: `order-sup-${id}`,
      memory_summary: "",
      wake_guidance: "",
      extra_instructions: [...(body.instructions || [])],
      next_wake_at: null,
      turns: 0,
      final_output: null,
      created_at: now,
      updated_at: now,
      _ctl: { events: [], newInstruction: false, paused: false, terminated: false, terminateReason: "terminated by user", nextWakeMs: null, sinceContinue: 0 },
    };
    load().runs.push(run);
    addEntry(id, "event", "order_created", `Order ${run.order_id} created`, "normal", "start", { type: "order_created", payload: run.order_context });
    runAgent(run, "start", null); // workflow start → first agent turn
    save();
    return respond(strip(run));
  },
  sendEvent: (id: string, type: string, payload: Record<string, unknown> = {}) => {
    const run = findRun(id);
    const event = { id: uid(), type, payload, received_at: new Date().toISOString() };
    addEntry(id, "event", type, Object.keys(payload).length ? JSON.stringify(payload) : "", "normal", "event", event);
    run._ctl.events.push(event); // signal: submit_event
    save();
    return respond(strip(run));
  },
  addInstruction: (id: string, text: string) => {
    const run = findRun(id);
    run.extra_instructions = [...run.extra_instructions, text];
    addEntry(id, "system", "Instruction added", text, "high", "instruction");
    run._ctl.newInstruction = true; // signal: add_instruction
    save();
    return respond(strip(run));
  },
  control: (id: string, action: "interrupt" | "resume" | "terminate") => {
    const run = findRun(id);
    if (action === "interrupt") { run._ctl.paused = true; addEntry(id, "system", "Run paused", "", "high"); }
    if (action === "resume") { run._ctl.paused = false; addEntry(id, "system", "Run resumed", "", "high"); }
    if (action === "terminate") { run._ctl.terminated = true; addEntry(id, "system", "Terminate requested", "", "high"); }
    save();
    return respond(strip(run));
  },

  // Demo-only helpers
  fastForward: (id: string) => {
    const run = findRun(id);
    if (run._ctl.nextWakeMs) {
      run._ctl.nextWakeMs = Date.now();
      addEntry(id, "system", "⏩ Fast-forwarded to the next scheduled wake-up", "Demo control — skips the durable timer.", "normal");
      tick();
    }
    return respond(strip(run));
  },
  reset: () => {
    db = seed();
    save();
    return respond(true);
  },
};
