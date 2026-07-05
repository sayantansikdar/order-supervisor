from .tools import tool_catalog

AGENT_SYSTEM = """You are an autonomous Order Supervisor agent. You oversee ONE order \
across its whole lifecycle. You are woken up occasionally — on start, when an \
important event arrives, or on a scheduled timer — reason about the situation, \
optionally act through tools, then go back to sleep. You do NOT run continuously.

Operating principles:
- Act only when it helps the order or customer. Otherwise, sleep.
- Respect the base instruction and any run-specific instructions (they override defaults).
- Choose a sensible next wake-up. Sooner when the order is fragile (payment/shipment \
problems, unresolved customer messages); much later when things are calm.
- When the order reaches a terminal state (delivered, cancelled, fully refunded), close.
- Keep a compact rolling memory summary — it is your long-term memory across turns.

Respond with ONLY a JSON object of this exact shape:
{
  "reasoning": "1-3 sentences of why",
  "tool_calls": [ {"tool": "<tool_name>", "args": { ... }} ],
  "memory_summary": "updated compact rolling summary of the whole order so far",
  "next_wake_seconds": <int>,
  "status": "active|sleeping|review",
  "should_close": <bool>,
  "wake_guidance": "short guidance for the wake classifier on what should wake you early"
}"""


def build_agent_user_prompt(ctx: dict) -> str:
    tools = tool_catalog(ctx["tools"])
    instructions = ctx["extra_instructions"] or ["(none)"]
    recent = ctx["recent_timeline"] or ["(no history yet)"]
    trigger = ctx["trigger"]
    event = ctx.get("event")
    event_str = "n/a"
    if event:
        event_str = f'{event["type"]} :: {event.get("payload", {})}'

    return f"""SUPERVISOR: {ctx["supervisor_name"]}
BASE INSTRUCTION: {ctx["base_instruction"]}
WAKE AGGRESSIVENESS: {ctx["wake_aggressiveness"]}
DEFAULT WAKE (s): {ctx["default_wake_seconds"]}

ORDER ID: {ctx["order_id"]}
ORDER CONTEXT: {ctx["order_context"]}

RUN-SPECIFIC INSTRUCTIONS:
- {chr(10).join('- ' + i for i in instructions).lstrip('- ')}

MEMORY SUMMARY (long-term):
{ctx["memory_summary"] or "(empty)"}

RECENT TIMELINE (newest last):
{chr(10).join(recent)}

AVAILABLE TOOLS:
{tools}

WHY YOU WOKE UP: {trigger}
TRIGGERING EVENT: {event_str}

Decide what to do now. Return only the JSON object."""


FINALIZE_SYSTEM = """You are closing out an Order Supervisor run. Produce a concise \
post-mortem. Respond with ONLY a JSON object:
{
  "final_summary": "what happened with this order, end to end",
  "important_actions": ["..."],
  "key_learnings": ["..."],
  "feedback": ["recommendations to improve future supervision"]
}"""


def build_finalize_user_prompt(ctx: dict) -> str:
    recent = ctx["recent_timeline"] or ["(no history)"]
    return f"""ORDER ID: {ctx["order_id"]}
FINAL STATUS: {ctx["status"]}
MEMORY SUMMARY:
{ctx["memory_summary"]}

FULL TIMELINE (newest last):
{chr(10).join(recent)}

Write the closeout JSON."""
