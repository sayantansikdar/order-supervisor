"""Temporal activities — all side effects (DB, LLM, tools) live here."""
from datetime import datetime

from temporalio import activity

from ..agent import runtime
from ..db import session_scope
from ..models import Run


@activity.defn
async def run_agent_activity(run_id: str, trigger: str, event: dict | None) -> dict:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return {"status": "failed", "next_wake_seconds": 60, "should_close": True,
                    "summary": "", "wake_guidance": ""}
        return await runtime.run_agent(session, run, trigger, event)


@activity.defn
async def classify_event_activity(run_id: str, event: dict) -> dict:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return {"wake": False, "importance": "low", "reason": "run missing"}
        return await runtime.classify(session, run, event)


@activity.defn
async def finalize_activity(run_id: str, reason: str, final_status: str) -> dict:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return {}
        # Flip to the terminal status first so the generated summary reflects it.
        run.status = final_status
        run.sleep_state = "awake"
        run.next_wake_at = None
        output = await runtime.finalize(session, run, reason)
        return output


@activity.defn
async def set_status_activity(run_id: str, status: str, sleep_state: str) -> None:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        run.status = status
        run.sleep_state = sleep_state
        if sleep_state == "awake":
            run.next_wake_at = None


@activity.defn
async def touch_run_activity(run_id: str) -> None:
    async with session_scope() as session:
        run = await session.get(Run, run_id)
        if run:
            run.updated_at = datetime.utcnow()
