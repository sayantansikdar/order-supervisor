from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- Supervisors ----------
class SupervisorCreate(BaseModel):
    name: str
    base_instruction: str
    tools: list[str] = Field(default_factory=list)
    default_wake_seconds: int = 120
    model: str = "claude-sonnet-4-6"
    wake_aggressiveness: str = "medium"


class SupervisorOut(BaseModel):
    id: str
    name: str
    base_instruction: str
    tools: list[str]
    default_wake_seconds: int
    model: str
    wake_aggressiveness: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Runs ----------
class RunCreate(BaseModel):
    supervisor_id: str
    order_id: str
    order_context: dict[str, Any] = Field(default_factory=dict)
    instructions: list[str] = Field(default_factory=list)


class TimelineOut(BaseModel):
    id: str
    kind: str
    title: str
    detail: str
    data: Optional[dict] = None
    importance: str
    trigger: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RunOut(BaseModel):
    id: str
    supervisor_id: str
    order_id: str
    order_context: dict[str, Any]
    status: str
    sleep_state: str
    workflow_id: Optional[str] = None
    memory_summary: str
    wake_guidance: str
    extra_instructions: list[str]
    next_wake_at: Optional[datetime] = None
    turns: int
    final_output: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunDetailOut(RunOut):
    timeline: list[TimelineOut] = Field(default_factory=list)
    supervisor: Optional[SupervisorOut] = None


class EventIn(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class InstructionIn(BaseModel):
    text: str
