"""Agent runtime — pure business logic invoked by Temporal activities.

Loads run context from the DB, asks the LLM (or the deterministic mock policy)
for a decision, executes the (mocked) tool calls, writes timeline + memory, and
returns a compact result the workflow uses to decide sleep/close.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Run, Supervisor, TimelineEntry
from . import llm, mock
from .prompts import (
    AGENT_SYSTEM,
    FINALIZE_SYSTEM,
    build_agent_user_prompt,
    build_finalize_user_prompt,
)
from .tools import TOOLS, simulate_tool

RECENT_LIMIT = 14


async def _recent_timeline(session: AsyncSession, run_id: str, limit: int = RECENT_LIMIT) -> list[str]:
    rows = (
        await session.execute(
            select(TimelineEntry)
            .where(TimelineEntry.run_id == run_id)
            .order_by(TimelineEntry.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    rows = list(reversed(rows))
    return [f"{r.created_at:%H:%M:%S} [{r.kind}] {r.title} — {r.detail}"[:200] for r in rows]


def _add_entry(session, run_id, kind, title, detail="", importance="normal", trigger=None, data=None):
    session.add(
        TimelineEntry(
            run_id=run_id,
            kind=kind,
            title=title,
            detail=detail,
            importance=importance,
            trigger=trigger,
            data=data,
        )
    )


async def _build_ctx(session: AsyncSession, run: Run, sup: Supervisor, trigger: str, event: dict | None) -> dict:
    return {
        "supervisor_name": sup.name,
        "base_instruction": sup.base_instruction,
        "wake_aggressiveness": sup.wake_aggressiveness,
        "default_wake_seconds": sup.default_wake_seconds,
        "tools": sup.tools or list(TOOLS.keys()),
        "order_id": run.order_id,
        "order_context": run.order_context,
        "extra_instructions": run.extra_instructions or [],
        "memory_summary": run.memory_summary,
        "recent_timeline": await _recent_timeline(session, run.id),
        "trigger": trigger,
        "event": event,
        "status": run.status,
    }


async def run_agent(session: AsyncSession, run: Run, trigger: str, event: dict | None):
    """Run one agent inference turn. Mutates + returns the run. Returns dict result."""
    sup = await session.get(Supervisor, run.supervisor_id)
    ctx = await _build_ctx(session, run, sup, trigger, event)

    decision = None
    if llm.llm_available():
        decision = await llm.complete_json(AGENT_SYSTEM, build_agent_user_prompt(ctx))
    if not decision:
        decision = mock.mock_agent_decision(ctx)

    # Record the agent's reasoning turn.
    _add_entry(
        session,
        run.id,
        "agent",
        f"Agent woke ({trigger})",
        decision.get("reasoning", ""),
        importance="normal",
        trigger=trigger,
    )

    should_close = bool(decision.get("should_close"))
    next_wake = int(decision.get("next_wake_seconds", sup.default_wake_seconds) or sup.default_wake_seconds)
    allowed = set(sup.tools or list(TOOLS.keys()))

    for call in decision.get("tool_calls", []):
        name = call.get("tool")
        args = call.get("args", {}) or {}
        if name not in TOOLS:
            continue
        if name not in allowed and not TOOLS[name].control:
            continue  # supervisor not granted this tool
        if name == "schedule_next_wake":
            next_wake = int(args.get("seconds", next_wake) or next_wake)
        if name == "close_workflow":
            should_close = True
        title, detail = simulate_tool(name, args)
        importance = "high" if name in ("escalate_issue", "mark_order_for_review") else "normal"
        _add_entry(session, run.id, "action", title, detail, importance=importance, trigger=trigger,
                   data={"tool": name, "args": args})

    # Update memory + lifecycle state.
    run.memory_summary = decision.get("memory_summary", run.memory_summary)
    run.wake_guidance = decision.get("wake_guidance", run.wake_guidance)
    run.turns = (run.turns or 0) + 1
    next_wake = max(5, min(next_wake, 86400))

    if should_close:
        run.sleep_state = "awake"
        run.status = "active"  # finalize step will flip to completed
    else:
        run.status = decision.get("status", run.status) or run.status
        if run.status not in ("review",):
            run.status = "sleeping" if next_wake > 0 else "active"
        run.sleep_state = "sleeping"
        run.next_wake_at = datetime.utcnow() + timedelta(seconds=next_wake)

    return {
        "status": run.status,
        "next_wake_seconds": next_wake,
        "should_close": should_close,
        "summary": run.memory_summary,
        "wake_guidance": run.wake_guidance,
    }


async def classify(session: AsyncSession, run: Run, event: dict) -> dict:
    sup = await session.get(Supervisor, run.supervisor_id)
    etype = event.get("type", "")
    result = None
    # The mock classifier is fast + deterministic; only reach for the LLM if you
    # want nuanced judgement. Here we keep classification rule-based for latency.
    result = mock.mock_classify(etype, sup.wake_aggressiveness, run.wake_guidance)

    _add_entry(
        session,
        run.id,
        "observation",
        f"Classifier: {'WAKE' if result['wake'] else 'defer'} — {etype}",
        result["reason"],
        importance=result["importance"],
        trigger="event",
        data={"event": event, "decision": result},
    )
    return result


async def finalize(session: AsyncSession, run: Run, reason: str) -> dict:
    sup = await session.get(Supervisor, run.supervisor_id)
    action_titles = (
        await session.execute(
            select(TimelineEntry.title)
            .where(TimelineEntry.run_id == run.id, TimelineEntry.kind == "action")
            .order_by(TimelineEntry.created_at)
        )
    ).scalars().all()

    ctx = {
        "order_id": run.order_id,
        "status": run.status,
        "memory_summary": run.memory_summary,
        "recent_timeline": await _recent_timeline(session, run.id, limit=40),
        "action_titles": list(action_titles),
    }

    output = None
    if llm.llm_available():
        output = await llm.complete_json(FINALIZE_SYSTEM, build_finalize_user_prompt(ctx))
    if not output:
        output = mock.mock_finalize(ctx)

    output["closed_reason"] = reason
    run.final_output = output
    _add_entry(
        session,
        run.id,
        "final",
        "Run closed — final summary generated",
        output.get("final_summary", ""),
        importance="high",
        data=output,
    )
    return output
