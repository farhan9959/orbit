import type { Run } from "../types";
import { detectionTick, failureTick, seriesFor } from "../lib/metrics";

interface Props {
  run: Run;
  tick: number;
  onTick: (tick: number) => void;
  playing: boolean;
  onPlayToggle: () => void;
  tickMs: number;
}

export function Timeline({ run, tick, onTick, playing, onPlayToggle, tickMs }: Props) {
  const last = run.frames.length - 1;
  const critical = seriesFor(run, "CRITICAL");
  const overall = seriesFor(run, "OVERALL");
  const injected = failureTick(run);
  const detected = detectionTick(run);
  const width = 600;
  const height = 70;

  const path = (values: (number | null)[]) =>
    values
      .map((value, index) => {
        const x = (index / Math.max(1, last)) * width;
        const y = height - (value ?? 0) * height;
        return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

  return (
    <section aria-labelledby="timeline-heading">
      <h3 id="timeline-heading" className="mb-2 font-semibold text-sm">
        Delivery over time
      </h3>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full rounded border border-slate-700 bg-slate-950"
        role="img"
        aria-label="Delivery ratio over the run for CRITICAL (solid) and overall (dashed)"
        style={{ height }}
      >
        {injected !== null && (
          <line
            x1={(injected / Math.max(1, last)) * width}
            x2={(injected / Math.max(1, last)) * width}
            y1={0}
            y2={height}
            stroke="#f26a6a"
            strokeWidth={1.5}
          />
        )}
        {detected !== null && (
          <line
            x1={(detected / Math.max(1, last)) * width}
            x2={(detected / Math.max(1, last)) * width}
            y1={0}
            y2={height}
            stroke="#ffb347"
            strokeDasharray="3 3"
            strokeWidth={1.5}
          />
        )}
        <path d={path(overall)} fill="none" stroke="#8ecae6" strokeWidth={1.5} strokeDasharray="4 3" />
        <path d={path(critical)} fill="none" stroke="#ff8fa3" strokeWidth={2} />
        <line
          x1={(tick / Math.max(1, last)) * width}
          x2={(tick / Math.max(1, last)) * width}
          y1={0}
          y2={height}
          stroke="#e8ecf8"
          strokeWidth={1}
        />
      </svg>
      <p className="mt-1 text-xs text-slate-300">
        <span style={{ color: "#ff8fa3" }}>——</span> CRITICAL ·{" "}
        <span style={{ color: "#8ecae6" }}>- -</span> overall ·{" "}
        <span style={{ color: "#f26a6a" }}>|</span> failure injected ·{" "}
        <span style={{ color: "#ffb347" }}>¦</span> detected by control plane
      </p>
      <div className="mt-2 flex items-center gap-3">
        <button
          type="button"
          onClick={onPlayToggle}
          className="rounded bg-slate-200 px-3 py-1 text-sm font-semibold text-slate-900 hover:bg-white"
          aria-pressed={playing}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <label className="flex flex-1 items-center gap-2 text-sm">
          <span className="whitespace-nowrap">
            Tick <span className="tabular-nums">{tick}</span> /{" "}
            <span className="tabular-nums">{last}</span>
          </span>
          <input
            type="range"
            min={0}
            max={last}
            value={tick}
            onChange={(event) => onTick(Number(event.target.value))}
            className="w-full"
            aria-label="Simulation tick"
            aria-valuetext={`tick ${tick} of ${last}, ${(tick * tickMs) / 1000} seconds`}
          />
          <span className="whitespace-nowrap tabular-nums text-slate-300">
            {((tick * tickMs) / 1000).toFixed(1)} s
          </span>
        </label>
      </div>
    </section>
  );
}
