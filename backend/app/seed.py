"""Seed a couple of ready-to-use supervisor templates on startup."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent.tools import DEFAULT_TOOL_NAMES
from .models import Supervisor

TEMPLATES = [
    {
        "name": "Standard Order Supervisor",
        "base_instruction": (
            "Watch this order end-to-end. Keep the customer informed, resolve payment and "
            "shipment problems quickly, escalate anything risky, and close out cleanly on delivery."
        ),
        "default_wake_seconds": 90,
        "wake_aggressiveness": "medium",
    },
    {
        "name": "High-Touch VIP Supervisor",
        "base_instruction": (
            "This is a VIP order. Be proactive and fast. Prefer over-communication with the "
            "customer, escalate delays immediately, and never let an issue sit unattended."
        ),
        "default_wake_seconds": 45,
        "wake_aggressiveness": "high",
    },
    {
        "name": "Hands-Off Compliance Supervisor",
        "base_instruction": (
            "Supervise conservatively. Do not contact the customer without human review. "
            "Prefer internal notes and reviews over direct action."
        ),
        "default_wake_seconds": 180,
        "wake_aggressiveness": "low",
    },
]


async def seed_supervisors(session: AsyncSession) -> None:
    existing = (await session.execute(select(Supervisor.name))).scalars().all()
    existing_names = set(existing)
    for tpl in TEMPLATES:
        if tpl["name"] in existing_names:
            continue
        session.add(
            Supervisor(
                name=tpl["name"],
                base_instruction=tpl["base_instruction"],
                tools=DEFAULT_TOOL_NAMES,
                default_wake_seconds=tpl["default_wake_seconds"],
                wake_aggressiveness=tpl["wake_aggressiveness"],
            )
        )
    await session.commit()
