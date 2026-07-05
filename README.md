# Order Supervisor

A POC for a **long-running AI supervisor** that oversees a single order from creation
until completion. Each order gets one long-running **Temporal** workflow. Events are
delivered into that workflow as signals. An AI agent decides when to **act now**, when
to **sleep**, and when to **wake up later** to re-check the situation.

- **Frontend:** Next.js (App Router) + Tailwind
- **Backend:** Python + FastAPI
- **Orchestration:** Temporal (`temporalio`)
- **Persistence:** PostgreSQL (Supabase works too)
- **Agent:** Claude (Anthropic) with a **deterministic mock fallback** so the whole
  product runs end-to-end with **no API key**.

> See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the design note.

---

## What it does

- Starts **one Temporal workflow per order**.
- The agent runs on **three triggers**: workflow start, incoming event/signal, and
  scheduled wake-up.
- Every incoming event is first checked by a **lightweight wake classifier** that
  decides whether it's important enough to wake the main agent now, or defer to the
  next scheduled review.
- Maintains a **timeline**, a **compact rolling memory summary**, current status, and
  the next wake-up time.
- Executes **6 mocked tools**: `send_customer_message`, `create_internal_note`,
  `escalate_issue`, `mark_order_for_review`, `schedule_next_wake`, `close_workflow`.
- Supports **per-run instructions added after start**, plus **pause / resume /
  terminate**.
- Produces a **final summary + key learnings + feedback** when the run ends.
- Uses `continue_as_new` to keep history bounded on very long-lived orders.

---

## Prerequisites

- Docker (for Postgres + Temporal dev server), **or** a local Postgres + the
  [Temporal CLI](https://docs.temporal.io/cli).
- Python 3.11+
- Node 18+

## 1. Start infrastructure

```bash
docker compose up -d
# Postgres → localhost:5432   Temporal → localhost:7233   Temporal UI → http://localhost:8233
```

<details>
<summary>No Docker? Run the pieces directly</summary>

```bash
# Postgres: use any local instance / Supabase and set DATABASE_URL
# Temporal dev server (single binary):
temporal server start-dev            # gRPC :7233, UI :8233
```
</details>

## 2. Backend (API + Temporal worker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optionally add ANTHROPIC_API_KEY

# Terminal A — API (creates tables + seeds supervisor templates on boot)
uvicorn app.main:app --reload --port 8000

# Terminal B — Temporal worker (runs workflows + activities)
python -m app.temporal_app.worker
```

> The agent runs on a deterministic mock policy that
> still reasons over events and instructions. Add a key + `USE_LLM=auto` to switch to
> the real model automatically.

## 3. Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev                   # http://localhost:3000
```

---

## Demo walkthrough

1. Open http://localhost:3000. Three supervisor templates are pre-seeded (see the
   **Supervisors** tab; create your own there too).
2. On **Runs**, pick a supervisor, optionally add run instructions such as
   *"If shipment is delayed, escalate immediately."*, and **Start run**.
3. You land on the run page. Watch the agent's **start** turn, its memory, and the
   **next wake-up** timer. It goes to **sleep**.
4. **Inject events** (buttons): `payment_failed`, `shipment_delayed`,
   `customer_message_received`, … Watch the classifier decide wake-vs-defer, the agent
   act through tools, and memory update. Routine events (e.g. `shipment_created` under a
   low/medium supervisor) are deferred to the next scheduled review.
5. Try `mystery_event` to see **unknown-event escalation**.
6. **Add an instruction** mid-run and see it change subsequent behavior.
7. **Pause / Resume / Terminate** from the controls.
8. Send `delivered` (or Terminate) to reach a terminal state and see the
   **final summary, learnings, and feedback**.

Scripted event stream instead of clicking:

```bash
cd backend
python scripts/generate_events.py <run_id>            # runs a scenario
python scripts/generate_events.py <run_id> payment_failed   # single event
```

---

## API surface

| Method | Path | Purpose |
| ------ | ---- | ------- |
| POST | `/api/supervisors` | create a supervisor template |
| GET  | `/api/supervisors` / `/{id}` | list / get supervisors |
| GET  | `/api/supervisors/tools` | list available tools |
| POST | `/api/runs` | start an order run (starts the workflow) |
| GET  | `/api/runs` / `/{id}` | list runs / run detail (timeline, memory) |
| POST | `/api/runs/{id}/events` | inject an event (workflow signal) |
| POST | `/api/runs/{id}/instructions` | add a run-specific instruction |
| POST | `/api/runs/{id}/interrupt` | pause |
| POST | `/api/runs/{id}/resume` | resume |
| POST | `/api/runs/{id}/terminate` | terminate |

---

## Notes / scope

This is a believable POC, not a production platform. No auth, no real integrations,
tools are simulated. Focus is on Temporal usage, long-running workflow modeling,
signal handling, wake/sleep behavior, and agent orchestration.
