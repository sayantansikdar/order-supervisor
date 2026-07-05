import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Supervisor(Base):
    """A reusable supervisor template / configuration."""

    __tablename__ = "supervisors"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    default_wake_seconds: Mapped[int] = mapped_column(Integer, default=120)
    model: Mapped[str] = mapped_column(String, default="claude-sonnet-4-6")
    # how eagerly the wake classifier escalates events: low | medium | high
    wake_aggressiveness: Mapped[str] = mapped_column(String, default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    runs: Mapped[list["Run"]] = relationship(back_populates="supervisor")


class Run(Base):
    """One long-running supervision run per order."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    supervisor_id: Mapped[str] = mapped_column(ForeignKey("supervisors.id"))
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    order_context: Mapped[dict] = mapped_column(JSON, default=dict)

    # created | active | sleeping | paused | review | completed | terminated | failed
    status: Mapped[str] = mapped_column(String, default="created")
    sleep_state: Mapped[str] = mapped_column(String, default="awake")  # awake | sleeping
    workflow_id: Mapped[str] = mapped_column(String, nullable=True)

    memory_summary: Mapped[str] = mapped_column(Text, default="")
    wake_guidance: Mapped[str] = mapped_column(Text, default="")
    extra_instructions: Mapped[list] = mapped_column(JSON, default=list)

    next_wake_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0)

    final_output: Mapped[dict] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    supervisor: Mapped["Supervisor"] = relationship(back_populates="runs")
    timeline: Mapped[list["TimelineEntry"]] = relationship(
        back_populates="run", order_by="TimelineEntry.created_at"
    )


class TimelineEntry(Base):
    """Ordered log of everything that happened in a run."""

    __tablename__ = "timeline_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    # event | action | agent | observation | system | final
    kind: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=True)
    importance: Mapped[str] = mapped_column(String, default="normal")  # low | normal | high
    trigger: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["Run"] = relationship(back_populates="timeline")


TERMINAL_STATUSES = {"completed", "terminated", "failed"}
