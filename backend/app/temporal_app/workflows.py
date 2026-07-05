"""OrderSupervisorWorkflow — one long-running workflow per order.

Deterministic by construction: all I/O (DB, LLM, tools, time-of-day) happens in
activities. The workflow only sequences the agent's wake/sleep lifecycle and
holds the small amount of in-memory control state fed by signals.
"""
import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from . import activities
    from ..config import get_settings
    from .shared import StartParams

# After this many agent turns we continue-as-new to keep history bounded.
# Resolved at worker import (a deploy-time constant), configurable via
# CONTINUE_AS_NEW_AFTER so the demo can trigger it quickly.
CONTINUE_AS_NEW_AFTER = get_settings().continue_as_new_after

_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1))
_TERMINAL = {"completed", "terminated", "failed"}


@workflow.defn
class OrderSupervisorWorkflow:
    def __init__(self) -> None:
        self._events: list[dict] = []
        self._new_instruction = False
        self._paused = False
        self._terminated = False
        self._terminate_reason = "terminated by user"
        self._status = "created"
        self._next_wake_seconds = 120
        self._turns = 0

    # ---------------- signals ----------------
    @workflow.signal
    async def submit_event(self, event: dict) -> None:
        self._events.append(event)

    @workflow.signal
    async def add_instruction(self, text: str) -> None:
        # The instruction text is persisted by the API; we just wake to react.
        self._new_instruction = True

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def terminate(self, reason: str) -> None:
        self._terminate_reason = reason or self._terminate_reason
        self._terminated = True

    # ---------------- queries ----------------
    @workflow.query
    def state(self) -> dict:
        return {
            "status": self._status,
            "paused": self._paused,
            "terminated": self._terminated,
            "pending_events": len(self._events),
            "next_wake_seconds": self._next_wake_seconds,
            "turns": self._turns,
        }

    # ---------------- helpers ----------------
    def _has_work(self) -> bool:
        # Paused is included so a pause signal interrupts sleep immediately.
        return (
            bool(self._events)
            or self._new_instruction
            or self._terminated
            or self._paused
        )

    async def _agent(self, run_id: str, trigger: str, event: dict | None = None) -> None:
        result = await workflow.execute_activity(
            activities.run_agent_activity,
            args=[run_id, trigger, event],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_RETRY,
        )
        self._status = result["status"]
        self._next_wake_seconds = max(1, int(result["next_wake_seconds"]))
        self._turns += 1
        if result["should_close"]:
            await self._finalize(run_id, "order reached terminal state", "completed")

    async def _finalize(self, run_id: str, reason: str, final_status: str) -> None:
        await workflow.execute_activity(
            activities.finalize_activity,
            args=[run_id, reason, final_status],
            start_to_close_timeout=timedelta(seconds=120),
            retry_policy=_RETRY,
        )
        self._status = final_status

    # ---------------- main ----------------
    @workflow.run
    async def run(self, params: StartParams) -> dict:
        run_id = params.run_id

        if not params.continued:
            await self._agent(run_id, "start")

        while self._status not in _TERMINAL:
            if self._terminated:
                await self._finalize(run_id, self._terminate_reason, "terminated")
                break

            # Sleep until the scheduled wake-up OR until a signal gives us work.
            timed_out = False
            try:
                await workflow.wait_condition(
                    self._has_work,
                    timeout=timedelta(seconds=self._next_wake_seconds),
                )
            except asyncio.TimeoutError:
                timed_out = True

            if self._terminated:
                await self._finalize(run_id, self._terminate_reason, "terminated")
                break

            if self._paused:
                # Stay paused (still queue events) until resumed or terminated.
                await workflow.execute_activity(
                    activities.set_status_activity,
                    args=[run_id, "paused", "awake"],
                    start_to_close_timeout=timedelta(seconds=30),
                )
                await workflow.wait_condition(lambda: not self._paused or self._terminated)
                continue

            if timed_out:
                await self._agent(run_id, "scheduled_wakeup")
            else:
                # Drain queued events through the classifier first.
                while self._events and self._status not in _TERMINAL:
                    event = self._events.pop(0)
                    decision = await workflow.execute_activity(
                        activities.classify_event_activity,
                        args=[run_id, event],
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=_RETRY,
                    )
                    if decision["wake"]:
                        await self._agent(run_id, "event", event)
                if self._new_instruction and self._status not in _TERMINAL:
                    self._new_instruction = False
                    await self._agent(run_id, "instruction")

            # Keep workflow history bounded on very long-lived orders.
            if self._turns >= CONTINUE_AS_NEW_AFTER and self._status not in _TERMINAL:
                workflow.continue_as_new(
                    StartParams(run_id=run_id, order_id=params.order_id, continued=True)
                )

        return {"run_id": run_id, "final_status": self._status}
