from dataclasses import dataclass, field
from typing import Any


@dataclass
class StartParams:
    run_id: str
    order_id: str
    # when a workflow continues-as-new we skip the initial "start" inference
    continued: bool = False


@dataclass
class OrderEvent:
    id: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: str = ""


@dataclass
class ClassifierDecision:
    wake: bool
    importance: str
    reason: str


@dataclass
class AgentResult:
    status: str
    next_wake_seconds: int
    should_close: bool
    summary: str
    wake_guidance: str
