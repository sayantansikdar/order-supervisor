"""End-to-end self-test with NO Docker required.

Runs the real OrderSupervisorWorkflow + activities against Temporal's built-in
time-skipping test server, backed by a throwaway SQLite database and the
deterministic mock agent. Proves the full lifecycle: start -> classify (defer vs
wake) -> agent -> tools -> terminal event -> finalize.

    pip install aiosqlite
    python scripts/selftest.py
"""
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./selftest.db")
os.environ.setdefault("USE_LLM", "false")
os.environ.setdefault("TEMPORAL_TASK_QUEUE", "selftest-queue")

from sqlalchemy import select  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Run, Supervisor, TimelineEntry  # noqa: E402
from app.seed import seed_supervisors  # noqa: E402
from app.temporal_app import activities  # noqa: E402
from app.temporal_app.shared import StartParams  # noqa: E402
from app.temporal_app.workflows import OrderSupervisorWorkflow  # noqa: E402


def ev(t: str) -> dict:
    return {"id": t, "type": t, "payload": {}, "received_at": ""}


async def main() -> None:
    if os.path.exists("selftest.db"):
        os.remove("selftest.db")
    await init_db()
    async with SessionLocal() as s:
        await seed_supervisors(s)
        sup = (await s.execute(select(Supervisor).where(Supervisor.wake_aggressiveness == "medium"))).scalars().first()
        run = Run(
            supervisor_id=sup.id, order_id="ORD-TEST", order_context={"item": "widget"},
            extra_instructions=["If shipment is delayed, escalate immediately."],
        )
        s.add(run)
        await s.flush()
        run.workflow_id = f"order-sup-{run.id}"
        run_id = run.id
        await s.commit()

    print("• starting time-skipping Temporal test server…")
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=os.environ["TEMPORAL_TASK_QUEUE"],
            workflows=[OrderSupervisorWorkflow],
            activities=[
                activities.run_agent_activity,
                activities.classify_event_activity,
                activities.finalize_activity,
                activities.set_status_activity,
                activities.touch_run_activity,
            ],
        ):
            handle = await env.client.start_workflow(
                OrderSupervisorWorkflow.run,
                StartParams(run_id=run_id, order_id="ORD-TEST"),
                id=f"order-sup-{run_id}",
                task_queue=os.environ["TEMPORAL_TASK_QUEUE"],
            )
            # routine event -> should be DEFERRED by the classifier (medium)
            await handle.signal(OrderSupervisorWorkflow.submit_event, ev("shipment_created"))
            # fragile event -> should WAKE + escalate (per run instruction)
            await handle.signal(OrderSupervisorWorkflow.submit_event, ev("shipment_delayed"))
            # terminal event -> agent closes the workflow
            await handle.signal(OrderSupervisorWorkflow.submit_event, ev("delivered"))
            result = await handle.result()
            print("• workflow result:", result)

    # ---- assertions against the DB ----
    async with SessionLocal() as s:
        run = await s.get(Run, run_id)
        rows = (await s.execute(select(TimelineEntry).where(TimelineEntry.run_id == run_id).order_by(TimelineEntry.created_at))).scalars().all()

    kinds = [(r.kind, r.title) for r in rows]
    actions = [r.title for r in rows if r.kind == "action"]
    observations = [r for r in rows if r.kind == "observation"]

    assert run.status == "completed", f"expected completed, got {run.status}"
    assert run.final_output, "no final output generated"
    assert any("Escalated" in a for a in actions), f"expected an escalation, got {actions}"
    deferred = [o for o in observations if "shipment_created" in o.title and "defer" in o.title]
    assert deferred, "shipment_created should have been deferred by the classifier"

    print("\n=== TIMELINE ===")
    for k, t in kinds:
        print(f"  [{k:11}] {t}")
    print("\n=== FINAL OUTPUT ===")
    for key, val in run.final_output.items():
        print(f"  {key}: {val}")
    print("\n✅ SELF-TEST PASSED — status:", run.status, "| turns:", run.turns)


if __name__ == "__main__":
    asyncio.run(main())
