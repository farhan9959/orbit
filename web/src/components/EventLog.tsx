import type { Run } from "../types";

const SEVERITY: Record<string, string> = {
  FAILURE_INJECTED: "border-l-red-400",
  CASCADE_FAILURE: "border-l-red-400",
  FAILURE_DETECTED: "border-l-amber-300",
  FLOW_PREEMPTED: "border-l-amber-300",
  FLOW_BLACKHOLED: "border-l-red-300",
  FLOW_REROUTED: "border-l-sky-300",
  RECONVERGED: "border-l-emerald-300",
};

function describe(payload: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(payload)) {
    parts.push(`${key}=${Array.isArray(value) ? value.join(",") : String(value)}`);
  }
  return parts.join(" ");
}

export function EventLog({ run, tick }: { run: Run; tick: number }) {
  const visible = run.events.filter((event) => event.t <= tick).slice(-60).reverse();
  return (
    <section aria-labelledby="events-heading" className="text-sm">
      <h3 id="events-heading" className="mb-2 font-semibold">
        Control-plane events
        <span className="ml-2 text-xs font-normal text-slate-300">
          {visible.length} shown of {run.eventCount} in run
        </span>
      </h3>
      {/* A scrollable region needs to be focusable or its content is unreachable without a
          mouse: axe flags this as scrollable-region-focusable, and it is a real WCAG 2.1 AA
          failure rather than a lint nit. tabIndex makes the list itself a tab stop so the
          arrow keys can scroll it. */}
      <ol
        className="max-h-64 overflow-y-auto rounded border border-slate-700 bg-slate-950 focus:outline focus:outline-2 focus:outline-sky-400"
        aria-live="polite"
        aria-label="Control-plane event log, scrollable"
        tabIndex={0}
      >
        {visible.length === 0 && (
          <li className="p-2 text-xs text-slate-400">No events yet at this tick.</li>
        )}
        {visible.map((event, index) => (
          <li
            key={`${event.t}-${event.type}-${index}`}
            className={`border-l-4 ${SEVERITY[event.type] ?? "border-l-slate-600"} border-b border-b-slate-800 px-2 py-1`}
          >
            <span className="tabular-nums text-xs text-slate-400">t{event.t}</span>{" "}
            <span className="font-medium">{event.type}</span>{" "}
            <span className="text-xs text-slate-300">{describe(event.payload)}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
