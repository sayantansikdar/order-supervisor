import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import get_settings
from ..db import get_session
from ..models import Run, Supervisor, TimelineEntry
from ..schemas import EventIn, InstructionIn, RunCreate, RunDetailOut, RunOut
from ..temporal_client import get_temporal_client
from ..temporal_app.shared import StartParams
from ..temporal_app.workflows import OrderSupervisorWorkflow

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _wf_id(run_id: str) -> str:
    return f"order-sup-{run_id}"


async def _handle(run: Run):
    client = await get_temporal_client()
    return client.get_workflow_handle(run.workflow_id or _wf_id(run.id))


async def _load(session: AsyncSession, run_id: str) -> Run:
    run = await session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    return run


@router.post("", response_model=RunOut)
async def create_run(body: RunCreate, session: AsyncSession = Depends(get_session)):
    sup = await session.get(Supervisor, body.supervisor_id)
    if not sup:
        raise HTTPException(404, "supervisor not found")

    # Assign the id up front so the workflow_id is stable and matches the run.
    run = Run(
        id=str(uuid.uuid4()),
        supervisor_id=sup.id,
        order_id=body.order_id,
        order_context=body.order_context,
        extra_instructions=list(body.instructions or []),
        status="created",
        next_wake_at=None,
    )
    run.workflow_id = _wf_id(run.id)
    session.add(run)
    await session.flush()

    # Seed the initial order_created event on the timeline.
    session.add(
        TimelineEntry(
            run_id=run.id, kind="event", title="order_created",
            detail=f"Order {run.order_id} created", trigger="start",
            data={"type": "order_created", "payload": body.order_context},
        )
    )
    await session.flush()

    settings = get_settings()
    client = await get_temporal_client()
    await client.start_workflow(
        OrderSupervisorWorkflow.run,
        StartParams(run_id=run.id, order_id=run.order_id),
        id=run.workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Run).order_by(Run.created_at.desc()))).scalars().all()
    return rows


@router.get("/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = (
        await session.execute(
            select(Run)
            .where(Run.id == run_id)
            .options(selectinload(Run.timeline), selectinload(Run.supervisor))
        )
    ).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "run not found")
    return run


@router.post("/{run_id}/events", response_model=RunOut)
async def inject_event(run_id: str, body: EventIn, session: AsyncSession = Depends(get_session)):
    run = await _load(session, run_id)
    event = {
        "id": str(uuid.uuid4()),
        "type": body.type,
        "payload": body.payload,
        "received_at": datetime.utcnow().isoformat(),
    }
    session.add(
        TimelineEntry(
            run_id=run.id, kind="event", title=body.type,
            detail=str(body.payload) if body.payload else "", trigger="event", data=event,
        )
    )
    await session.flush()
    handle = await _handle(run)
    await handle.signal(OrderSupervisorWorkflow.submit_event, event)
    return run


@router.post("/{run_id}/instructions", response_model=RunOut)
async def add_instruction(run_id: str, body: InstructionIn, session: AsyncSession = Depends(get_session)):
    run = await _load(session, run_id)
    run.extra_instructions = list(run.extra_instructions or []) + [body.text]
    session.add(
        TimelineEntry(
            run_id=run.id, kind="system", title="Instruction added",
            detail=body.text, importance="high", trigger="instruction",
        )
    )
    await session.flush()
    handle = await _handle(run)
    await handle.signal(OrderSupervisorWorkflow.add_instruction, body.text)
    return run


@router.post("/{run_id}/interrupt", response_model=RunOut)
async def interrupt_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await _load(session, run_id)
    handle = await _handle(run)
    await handle.signal(OrderSupervisorWorkflow.pause)
    session.add(TimelineEntry(run_id=run.id, kind="system", title="Run paused", importance="high"))
    return run


@router.post("/{run_id}/resume", response_model=RunOut)
async def resume_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await _load(session, run_id)
    handle = await _handle(run)
    await handle.signal(OrderSupervisorWorkflow.resume)
    session.add(TimelineEntry(run_id=run.id, kind="system", title="Run resumed", importance="high"))
    return run


@router.post("/{run_id}/terminate", response_model=RunOut)
async def terminate_run(run_id: str, session: AsyncSession = Depends(get_session)):
    run = await _load(session, run_id)
    handle = await _handle(run)
    await handle.signal(OrderSupervisorWorkflow.terminate, "terminated by user")
    session.add(TimelineEntry(run_id=run.id, kind="system", title="Terminate requested", importance="high"))
    return run
