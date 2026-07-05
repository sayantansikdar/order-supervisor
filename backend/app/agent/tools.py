"""Mocked supervisor tools.

Every tool is simulated (no real integrations) and produces a human-readable
result plus a timeline "action" entry. Two tools — schedule_next_wake and
close_workflow — are control tools interpreted by the agent runtime/workflow.
"""
from dataclasses import dataclass


@dataclass
class ToolSpec:
    name: str
    description: str
    control: bool = False  # control tools influence sleep/lifecycle


TOOLS: dict[str, ToolSpec] = {
    "send_customer_message": ToolSpec(
        "send_customer_message", "Send a message to the customer (email/SMS)."
    ),
    "create_internal_note": ToolSpec(
        "create_internal_note", "Record an internal note for the ops team."
    ),
    "escalate_issue": ToolSpec(
        "escalate_issue", "Escalate the order to a human ops agent."
    ),
    "mark_order_for_review": ToolSpec(
        "mark_order_for_review", "Flag the order for manual review."
    ),
    "schedule_next_wake": ToolSpec(
        "schedule_next_wake", "Set when the supervisor should wake up next.", control=True
    ),
    "close_workflow": ToolSpec(
        "close_workflow", "End supervision — the order reached a terminal state.", control=True
    ),
}

DEFAULT_TOOL_NAMES = list(TOOLS.keys())


def tool_catalog(tool_names: list[str]) -> str:
    lines = []
    for name in tool_names:
        spec = TOOLS.get(name)
        if spec:
            lines.append(f"- {spec.name}: {spec.description}")
    return "\n".join(lines)


def simulate_tool(name: str, args: dict) -> tuple[str, str]:
    """Return (title, detail) describing the simulated side effect."""
    if name == "send_customer_message":
        msg = args.get("message", "(no content)")
        return "📧 Sent customer message", msg
    if name == "create_internal_note":
        return "📝 Internal note", args.get("text", "(empty)")
    if name == "escalate_issue":
        return "🚨 Escalated to human ops", args.get("reason", "(no reason)")
    if name == "mark_order_for_review":
        return "🔎 Marked order for review", args.get("reason", "(no reason)")
    if name == "schedule_next_wake":
        secs = args.get("seconds", "?")
        return "⏰ Scheduled next wake-up", f"in {secs}s"
    if name == "close_workflow":
        return "✅ Closing supervision", args.get("reason", "(terminal state reached)")
    return f"🔧 {name}", str(args)
