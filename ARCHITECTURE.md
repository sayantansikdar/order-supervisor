# Architecture Note

## Overview

```
┌─────────────┐   REST    ┌──────────────┐   signals/start   ┌────────────────────┐
│  Next.js UI │ ────────▶ │  FastAPI     │ ────────────────▶ │  Temporal Server   │
│ (App Router)│ ◀──────── │  (API)       │                   │  (dev server)      │
└─────────────┘  polling  └──────┬───────┘                   └─────────┬──────────┘
                                 │ read/write                          │ dispatches
                                 ▼                                     ▼
                          ┌──────────────┐   activities   ┌────────────────────────┐
                          │  PostgreSQL  │ ◀───────────── │  Temporal Worker       │
                          │  runs, timeline,              │  • OrderSupervisorWF    │
                          │  memory, supervisors          │  • activities (DB/LLM)  │
                          └──────────────┘                └───────────┬────────────┘
                                                                      │
                                                            ┌─────────▼─────────┐
                                                            │ Agent runtime     │
                                                            │ Claude ⟷ mock     │
                                                            └───────────────────┘
```

- **FastAPI** owns run/supervisor CRUD and translates HTTP calls into Temporal
  operations (`start_workflow`, `signal`). It never runs agent logic itself.
- **Temporal workflow** (`OrderSupervisorWorkflow`) is the durable brain of a single
  order. One workflow == one order, alive until terminal.
- **Temporal worker** hosts the workflow and all **activities**. Activities are where
  every side effect lives (DB, LLM calls, tool simulation), keeping the workflow
  deterministic.
- **PostgreSQL** is the source of truth for the UI: runs, timeline, memory, final
  output. The workflow keeps only tiny in-memory control state.

## The three agent triggers

The workflow's run loop sleeps on `workflow.wait_condition(..., timeout=next_wake)`:

1. **Start** — first agent turn when the workflow begins.
2. **Event / signal** — `submit_event` appends to an in-workflow queue and wakes the
   loop; each queued event goes through the **classifier activity** first, and only
   `wake=true` events trigger a main-agent turn. Others are recorded and deferred.
3. **Scheduled wake-up** — when the sleep timer times out, the agent runs a
   `scheduled_wakeup` review and picks a new sleep duration.

This gives true **event-driven wake/sleep** without a hot loop: between turns the
workflow is genuinely idle (a durable Temporal timer), not polling.

## Wake classifier (lightweight policy)

`classify_event_activity` is rule-based and fast: some events are always important
(`payment_failed`, `refund_requested`, `shipment_delayed`, `customer_message_received`,
`delivered`), unknown events always wake (defensive escalation), and routine events
(`payment_confirmed`, `shipment_created`, `no_update_for_n_hours`) are gated by the
supervisor's `wake_aggressiveness` (low/medium/high). The main agent also emits
`wake_guidance` each turn that the classifier can consult — a hook for
agent-generated wake policy.

## Memory & timeline

- **Timeline** (`timeline_entries`): an append-only log of everything —
  `event`, `observation` (classifier), `agent` (reasoning), `action` (tool calls),
  `system` (pause/instruction), `final`. This is what the UI renders.
- **Memory summary**: a **compact rolling summary** the agent rewrites every turn. It
  is the agent's long-term memory across turns.
- **Compaction**: each agent turn only receives the memory summary + the last ~14
  timeline lines, not the full history. The mock policy also caps the rolling summary
  to the last 8 lines with an "(+N earlier events summarized)" header. The LLM path
  rewrites the summary each turn, folding old detail into prose.

## Tools

Six tools, all simulated. Two are **control tools** interpreted by the runtime/workflow:
`schedule_next_wake` (sets the next sleep) and `close_workflow` (drives finalization).
The rest produce timeline `action` entries. A supervisor grants a subset of tools;
the runtime refuses tool calls the supervisor wasn't granted.

## Lifecycle & control signals

| Signal | Effect |
| ------ | ------ |
| `submit_event(event)` | queue an event for classification |
| `add_instruction(text)` | wake to fold a new run instruction into context |
| `pause` / `resume` | pause interrupts sleep immediately; events keep queuing |
| `terminate(reason)` | finalize with a terminated status |

`state()` query exposes live control state for debugging.

Terminal states: `completed` (agent closed on a terminal order event),
`terminated` (user), `failed`.

## Long histories

After `CONTINUE_AS_NEW_AFTER` agent turns the workflow calls `continue_as_new`,
carrying only `run_id`/`order_id` (all real state is in Postgres), so a very
long-lived order never accumulates unbounded Temporal history.

## LLM strategy

`agent/llm.py` is the only place that imports the Anthropic SDK. If no key is present
(or a call fails), the runtime falls back to `agent/mock.py`, a deterministic policy
that reads the trigger, event type, and instructions (keyword matching for
"escalate delays", "no customer contact", "prioritize speed") and returns the exact
same JSON shape the model would. This keeps the demo reliable and offline-capable,
which for a POC matters more than model sophistication. The system prompt is sent as a
cached block for cheap repeated turns.

## Key files

```
backend/app/
  temporal_app/workflows.py   # OrderSupervisorWorkflow — wake/sleep/signals/CAN
  temporal_app/activities.py  # DB/LLM side effects
  agent/runtime.py            # load ctx → decide → run tools → persist
  agent/mock.py               # deterministic fallback policy
  agent/classifier logic      # in runtime.classify + mock.mock_classify
  api/runs.py                 # start workflow + signal on every action
frontend/app/runs/[runId]/    # live monitoring + control surface
```
