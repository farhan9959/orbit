import type { Frame, PriorityName, Run } from "../types";
import { PRIORITIES } from "../types";
import { formatRatio, formatSeconds, frameRatio, overallFrameRatio } from "../lib/metrics";
import { PRIORITY_COLOUR, PRIORITY_GLYPH } from "../lib/health";

interface Props {
  run: Run;
  frame: Frame;
  label: string;
}

function Bar({ value }: { value: number | null }) {
  const pct = value === null ? 0 : Math.round(value * 100);
  return (
    <div className="h-2 w-full rounded bg-slate-700" aria-hidden="true">
      <div className="h-2 rounded bg-slate-300" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function MetricsPanel({ run, frame, label }: Props) {
  const overall = overallFrameRatio(frame);
  return (
    <section aria-labelledby={`metrics-${label}`} className="text-sm">
      <h3 id={`metrics-${label}`} className="mb-2 font-semibold">
        Delivery ratio this tick
      </h3>
      <table className="w-full border-collapse">
        <caption className="sr-only">
          Per-priority delivery ratio at tick {frame.t} for {label}
        </caption>
        <thead>
          <tr className="text-left text-xs text-slate-300">
            <th scope="col" className="py-1">Class</th>
            <th scope="col" className="py-1">Ratio</th>
            <th scope="col" className="py-1 w-1/2">Level</th>
          </tr>
        </thead>
        <tbody>
          {PRIORITIES.map((priority: PriorityName) => {
            const ratio = frameRatio(frame, priority);
            return (
              <tr key={priority} className="border-t border-slate-800">
                <th scope="row" className="py-1 font-normal">
                  <span aria-hidden="true" style={{ color: PRIORITY_COLOUR[priority] }}>
                    {PRIORITY_GLYPH[priority]}
                  </span>{" "}
                  {priority}
                </th>
                <td className="py-1 tabular-nums">{formatRatio(ratio)}</td>
                <td className="py-1"><Bar value={ratio} /></td>
              </tr>
            );
          })}
          <tr className="border-t border-slate-700 font-semibold">
            <th scope="row" className="py-1">OVERALL</th>
            <td className="py-1 tabular-nums">{formatRatio(overall)}</td>
            <td className="py-1"><Bar value={overall} /></td>
          </tr>
        </tbody>
      </table>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <dt className="text-slate-300">Blackholed flows now</dt>
        <dd className="tabular-nums">{frame.blackholed}</dd>
        <dt className="text-slate-300">Run PDR (CRITICAL)</dt>
        <dd className="tabular-nums">{formatRatio(run.pdr.CRITICAL)}</dd>
        <dt className="text-slate-300">Run PDR (overall)</dt>
        <dd className="tabular-nums">{formatRatio(run.pdr.OVERALL)}</dd>
        <dt className="text-slate-300">Control-plane time</dt>
        <dd className="tabular-nums">{formatSeconds(run.controlSeconds)}</dd>
        <dt className="text-slate-300">Recomputations</dt>
        <dd className="tabular-nums">{run.controlCalls}</dd>
      </dl>
    </section>
  );
}
