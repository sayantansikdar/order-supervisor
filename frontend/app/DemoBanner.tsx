"use client";

import { DEMO } from "../lib/api";
import { demoApi } from "../lib/demo";

export default function DemoBanner() {
  if (!DEMO) return null;
  return (
    <div className="border-b border-indigo-200 bg-indigo-50 text-indigo-900">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-2 text-xs">
        <p>
          <b>Live demo.</b> The FastAPI + Temporal backend is simulated in your browser with the
          repo&apos;s deterministic agent policy; state is kept in localStorage, so runs survive a
          reload. To run it for real, see the{" "}
          <a className="underline" href="https://github.com/sayantansikdar/order-supervisor#readme">
            README
          </a>
          .
        </p>
        <button
          onClick={async () => {
            await demoApi.reset();
            window.location.reload();
          }}
          className="rounded border border-indigo-300 bg-white px-2 py-0.5 font-medium hover:bg-indigo-100"
        >
          Reset demo
        </button>
      </div>
    </div>
  );
}
