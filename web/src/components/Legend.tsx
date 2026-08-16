import { linkHealth } from "../lib/health";

const LEVELS: { utilisation: number; down: boolean; description: string }[] = [
  { utilisation: 0, down: true, description: "failed, carries nothing" },
  { utilisation: 0.99, down: false, description: "at or above 95% capacity" },
  { utilisation: 0.8, down: false, description: "70–95% capacity" },
  { utilisation: 0.3, down: false, description: "carrying traffic" },
  { utilisation: 0, down: false, description: "idle" },
];

export function Legend() {
  return (
    <section aria-labelledby="legend-heading" className="text-xs">
      <h3 id="legend-heading" className="mb-1 font-semibold text-slate-200">
        Link status
      </h3>
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {LEVELS.map(({ utilisation, down, description }) => {
          const health = linkHealth(utilisation, down);
          return (
            <li key={health.level} className="flex items-center gap-1.5">
              <span aria-hidden="true" style={{ color: health.colour }}>
                {health.glyph}
              </span>
              <span className="text-slate-200">{health.label}</span>
              <span className="text-slate-400">({description})</span>
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-slate-400">
        Status is encoded by glyph, line style and text as well as colour, so it does not rely
        on colour vision. Failed nodes are drawn as squares marked ✕; healthy nodes as circles.
      </p>
    </section>
  );
}
