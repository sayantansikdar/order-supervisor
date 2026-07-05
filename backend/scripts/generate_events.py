"""Simple CLI event generator.

Usage:
  python scripts/generate_events.py <run_id>                 # run a scripted scenario
  python scripts/generate_events.py <run_id> payment_failed  # send one event

Sends events into a run via the backend API (which signals the workflow).
"""
import sys
import time

import httpx

API = "http://localhost:8000"

SCENARIO = [
    ("payment_confirmed", {}),
    ("shipment_created", {"carrier": "UPS", "tracking": "1Z999"}),
    ("shipment_delayed", {"reason": "weather", "eta_days": 3}),
    ("customer_message_received", {"text": "Where is my order?"}),
    ("delivered", {}),
]


def send(run_id: str, etype: str, payload: dict):
    r = httpx.post(f"{API}/api/runs/{run_id}/events", json={"type": etype, "payload": payload}, timeout=30)
    r.raise_for_status()
    print(f"→ sent {etype} ({r.status_code})")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    run_id = sys.argv[1]
    if len(sys.argv) >= 3:
        send(run_id, sys.argv[2], {})
        return
    for etype, payload in SCENARIO:
        send(run_id, etype, payload)
        time.sleep(4)


if __name__ == "__main__":
    main()
