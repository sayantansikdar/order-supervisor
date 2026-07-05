from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.tools import DEFAULT_TOOL_NAMES, TOOLS
from ..db import get_session
from ..models import Supervisor
from ..schemas import SupervisorCreate, SupervisorOut

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.get("/tools")
async def list_tools() -> list[dict]:
    return [{"name": s.name, "description": s.description, "control": s.control} for s in TOOLS.values()]


@router.post("", response_model=SupervisorOut)
async def create_supervisor(body: SupervisorCreate, session: AsyncSession = Depends(get_session)):
    sup = Supervisor(
        name=body.name,
        base_instruction=body.base_instruction,
        tools=body.tools or DEFAULT_TOOL_NAMES,
        default_wake_seconds=body.default_wake_seconds,
        model=body.model,
        wake_aggressiveness=body.wake_aggressiveness,
    )
    session.add(sup)
    await session.flush()
    await session.refresh(sup)
    return sup


@router.get("", response_model=list[SupervisorOut])
async def list_supervisors(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Supervisor).order_by(Supervisor.created_at))).scalars().all()
    return rows


@router.get("/{supervisor_id}", response_model=SupervisorOut)
async def get_supervisor(supervisor_id: str, session: AsyncSession = Depends(get_session)):
    sup = await session.get(Supervisor, supervisor_id)
    if not sup:
        raise HTTPException(404, "supervisor not found")
    return sup
