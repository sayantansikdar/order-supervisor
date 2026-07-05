"""Deterministic, believable agent policy used when no LLM key is configured.

Keeps the whole product working end-to-end offline. It reads the trigger, the
event type, and any run-specific instructions (via keyword matching) and returns
the same JSON shape the LLM would.
"""
from typing import Any

# Events that clearly indicate the order reached a terminal state.
TERMINAL_EVENTS = {"delivered", "order_cancelled", "refund_completed"}


def _instr_flags(instructions: list[str]) -> dict[str, bool]:
    text = " ".join(instructions).lower()
    return {
        "escalate_delays": "delay" in text and "escalat" in text,
        "no_contact": ("human review" in text and "contact" in text)
        or "do not contact" in text
        or "don't contact" in text,
        "speed": "speed" in text or "prioritize speed" in text,
    }


def mock_agent_decision(ctx: dict[str, Any]) -> dict:
    trigger = ctx["trigger"]
    event = ctx.get("event") or {}
    etype = event.get("type", "")
    default_wake = int(ctx.get("default_wake_seconds", 120))
    flags = _instr_flags(ctx.get("extra_instructions", []))
    prev_memory = ctx.get("memory_summary", "")

    calls: list[dict] = []
    status = "sleeping"
    should_close = False
    next_wake = default_wake
    reasoning = ""
    guidance = "Wake early on payment_failed, shipment_delayed, refund_requested, customer_message_received or unknown events."

    def note(text: str):
        calls.append({"tool": "create_internal_note", "args": {"text": text}})

    def message(msg: str):
        # Respect "no customer contact without review" instruction.
        if flags["no_contact"]:
            calls.append({"tool": "mark_order_for_review", "args": {"reason": "Customer contact requires human review: " + msg}})
        else:
            calls.append({"tool": "send_customer_message", "args": {"message": msg}})

    if trigger == "start":
        note(f"Supervision started for order {ctx['order_id']}. Watching lifecycle.")
        reasoning = "New order — establishing supervision and a calm watch interval."
        status = "active"
        next_wake = default_wake
    elif trigger == "instruction":
        latest = (ctx.get("extra_instructions") or ["(none)"])[-1]
        note(f"Acknowledged new instruction: {latest}")
        reasoning = "Absorbed a new run-specific instruction; will apply it going forward."
        next_wake = max(30, default_wake // 2)
    elif etype == "payment_failed":
        message("We noticed your payment didn't go through. Please retry or update your payment method.")
        calls.append({"tool": "escalate_issue", "args": {"reason": "Payment failed — revenue at risk."}})
        reasoning = "Payment failed — nudged the customer and escalated for a quick recovery."
        next_wake = 45
        status = "review"
    elif etype == "refund_requested":
        calls.append({"tool": "mark_order_for_review", "args": {"reason": "Refund requested by customer."}})
        note("Refund requested — flagged for review per policy.")
        reasoning = "Refund request needs a human decision; flagged and staying close."
        next_wake = 60
        status = "review"
    elif etype == "shipment_delayed":
        message("Your shipment is running late — apologies. We're on it and will keep you posted.")
        if flags["escalate_delays"]:
            calls.append({"tool": "escalate_issue", "args": {"reason": "Shipment delayed and run instruction demands immediate escalation."}})
            reasoning = "Shipment delayed; run instruction says escalate immediately, so I did."
        else:
            note("Shipment delayed — proactively informed customer, monitoring closely.")
            reasoning = "Shipment delayed; reassured the customer and tightened the watch interval."
        next_wake = 45 if not flags["speed"] else 30
    elif etype == "customer_message_received":
        message("Thanks for reaching out — we've got your message and are looking into it right now.")
        reasoning = "Customer reached out; acknowledged quickly to keep them informed."
        next_wake = 60
    elif etype == "payment_confirmed":
        note("Payment confirmed. Order funded and healthy.")
        reasoning = "Payment cleared — nothing to do but relax the watch interval."
        next_wake = max(default_wake, 180)
    elif etype == "shipment_created":
        note("Shipment created and in transit. Tracking.")
        reasoning = "Shipment on its way; calm state, longer sleep."
        next_wake = max(default_wake, 180)
    elif etype == "no_update_for_n_hours":
        note("No updates for a while — proactively checking order health.")
        reasoning = "Quiet period; did a health check, nothing actionable yet."
        next_wake = default_wake
    elif etype in TERMINAL_EVENTS or etype == "delivered":
        note(f"Order reached terminal state via '{etype}'. Wrapping up supervision.")
        calls.append({"tool": "close_workflow", "args": {"reason": f"Order {etype}."}})
        reasoning = "Order is complete — closing the supervision workflow."
        should_close = True
        status = "active"
    elif trigger == "scheduled_wakeup":
        note("Scheduled review — order steady, no intervention needed.")
        reasoning = "Timer fired; reviewed state and found nothing needing action."
        next_wake = min(default_wake * 2, 600)
    else:
        # Unknown / unhandled event — escalate per good-to-have behavior.
        calls.append({"tool": "escalate_issue", "args": {"reason": f"Unknown event '{etype}' — needs human eyes."}})
        note(f"Unrecognized event '{etype}'. Escalated to be safe.")
        reasoning = "Unfamiliar event; escalated rather than guessing."
        next_wake = 60
        status = "review"

    memory = _roll_memory(prev_memory, trigger, etype, reasoning)
    return {
        "reasoning": reasoning,
        "tool_calls": calls,
        "memory_summary": memory,
        "next_wake_seconds": next_wake,
        "status": status,
        "should_close": should_close,
        "wake_guidance": guidance,
    }


def _roll_memory(prev: str, trigger: str, etype: str, reasoning: str) -> str:
    tag = etype or trigger
    line = f"[{tag}] {reasoning}"
    lines = [l for l in prev.split("\n") if l.strip()]
    lines.append(line)
    # keep a rolling window (compaction): last 8 memory lines
    if len(lines) > 8:
        head = f"(+{len(lines) - 8} earlier events summarized)"
        lines = [head] + lines[-8:]
    return "\n".join(lines)


def mock_classify(etype: str, aggressiveness: str, guidance: str) -> dict:
    always = {
        "payment_failed",
        "refund_requested",
        "shipment_delayed",
        "customer_message_received",
        "delivered",
        "order_cancelled",
    }
    calm = {"payment_confirmed", "shipment_created", "no_update_for_n_hours"}
    known = always | calm | {"order_created"}

    if etype in always:
        return {"wake": True, "importance": "high", "reason": f"'{etype}' always warrants immediate attention."}
    if etype not in known:
        return {"wake": True, "importance": "high", "reason": f"Unknown event '{etype}' — waking to be safe."}
    if aggressiveness == "high":
        return {"wake": True, "importance": "normal", "reason": "High-aggressiveness policy wakes on every event."}
    if aggressiveness == "low":
        return {"wake": False, "importance": "low", "reason": f"'{etype}' is routine; staying asleep until scheduled review."}
    # medium
    return {"wake": False, "importance": "low", "reason": f"'{etype}' is routine; will fold into the next scheduled review."}


def mock_finalize(ctx: dict) -> dict:
    actions = [t for t in (ctx.get("action_titles") or [])]
    return {
        "final_summary": (
            f"Supervised order {ctx['order_id']} from creation to terminal state "
            f"'{ctx['status']}'. {ctx.get('memory_summary','').splitlines()[-1] if ctx.get('memory_summary') else ''}"
        ).strip(),
        "important_actions": actions[-8:] or ["No interventions were required."],
        "key_learnings": [
            "Most lifecycle events were routine and safely deferred to scheduled reviews.",
            "Payment and shipment problems were the main triggers for active intervention.",
        ],
        "feedback": [
            "Tune wake aggressiveness per merchant risk profile.",
            "Consider auto-drafting customer messages for faster human approval when contact needs review.",
        ],
    }
