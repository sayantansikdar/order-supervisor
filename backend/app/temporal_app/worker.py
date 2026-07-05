"""Temporal worker entrypoint.

Run alongside the API:  python -m app.temporal_app.worker
"""
import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from ..config import get_settings
from . import activities
from .workflows import OrderSupervisorWorkflow


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    print(f"[worker] connected to {settings.temporal_host}, queue={settings.temporal_task_queue}")

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[OrderSupervisorWorkflow],
        activities=[
            activities.run_agent_activity,
            activities.classify_event_activity,
            activities.finalize_activity,
            activities.set_status_activity,
            activities.touch_run_activity,
        ],
    )
    print("[worker] running — waiting for tasks...")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
