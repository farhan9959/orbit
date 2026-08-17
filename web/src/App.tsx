import { useEffect, useMemo, useState } from "react";
import type { AlgorithmName, Demo, Results } from "./types";
import { ALGORITHMS } from "./types";
import { TopologyCanvas } from "./components/TopologyCanvas";
import { MetricsPanel } from "./components/MetricsPanel";
import { EventLog } from "./components/EventLog";
import { Timeline } from "./components/Timeline";
import { ResultsTable } from "./components/ResultsTable";
import { Legend } from "./components/Legend";
import { LivePanel } from "./components/LivePanel";

type Mode = "replay" | "live";

export default function App() {
  const [mode, setMode] = useState<Mode>("replay");
  const [demo, setDemo] = useState<Demo | null>(null);
  const [results, setResults] = useState<Results | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [primary, setPrimary] = useState<AlgorithmName>("orbit");
  const [comparison, setComparison] = useState<AlgorithmName>("cspf");
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`${import.meta.env.BASE_URL}data/demo.json`).then((r) => r.json()),
      fetch(`${import.meta.env.BASE_URL}data/results.json`).then((r) => r.json()),
    ])
      .then(([demoData, resultData]) => {
        setDemo(demoData as Demo);
        setResults(resultData as Results);
      })
      .catch(() => setError("Could not load results. Run `make web-data` first."));
  }, []);

  const lastTick = demo ? demo.runs[primary].frames.length - 1 : 0;

  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => {
      setTick((current) => (current >= lastTick ? 0 : current + 1));
    }, 80);
    return () => window.clearInterval(timer);
  }, [playing, lastTick]);

  const headline = useMemo(() => results?.["a8-headline"], [results]);

  const modeSwitch = (
    <div role="group" aria-label="View mode" className="flex gap-2">
      {(["replay", "live"] as const).map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={mode === option}
          onClick={() => setMode(option)}
          className={`rounded border px-3 py-1 text-sm ${
            mode === option
              ? "border-slate-300 bg-slate-700 font-semibold"
              : "border-slate-600 bg-slate-900"
          }`}
        >
          {option === "replay" ? "Replay committed runs" : "Live session"}
        </button>
      ))}
    </div>
  );

  if (mode === "live") {
    return (
      <div className="mx-auto max-w-[1400px] p-4 md:p-6">
        <header className="mb-4">
          <h1 className="text-2xl font-bold">ORBIT</h1>
        </header>
        <div className="mb-4">{modeSwitch}</div>
        <LivePanel />
      </div>
    );
  }

  if (error) {
    return (
      <main className="p-8">
        <h1 className="text-xl font-bold">ORBIT</h1>
        <div className="my-4">{modeSwitch}</div>
        <p className="mt-2 text-red-300">{error}</p>
      </main>
    );
  }

  if (!demo) {
    return (
      <main className="p-8">
        <p aria-live="polite">Loading results…</p>
      </main>
    );
  }

  const primaryRun = demo.runs[primary];
  const comparisonRun = demo.runs[comparison];
  const frame = primaryRun.frames[Math.min(tick, primaryRun.frames.length - 1)];
  const comparisonFrame = comparisonRun.frames[Math.min(tick, comparisonRun.frames.length - 1)];

  return (
    <div className="mx-auto max-w-[1400px] p-4 md:p-6">
      <header className="mb-4">
        <h1 className="text-2xl font-bold">ORBIT — recovery replay</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-300">
          A viewer over completed runs. It replays committed simulation output and never
          simulates, so nothing shown here can disagree with the results files. Scenario:{" "}
          <code className="text-slate-200">{demo.scenario}</code>.
        </p>
        <p className="mt-1 text-sm text-amber-200">
          Research prototype. Not validated for real emergency or medical infrastructure.
        </p>
      </header>

      <section aria-labelledby="controls-heading" className="mb-4">
        <h2 id="controls-heading" className="sr-only">
          View mode and algorithm selection
        </h2>
        <div className="mb-3">{modeSwitch}</div>
        <div className="flex flex-wrap gap-4">
          {(
            [
              ["Primary", primary, setPrimary],
              ["Compare against", comparison, setComparison],
            ] as const
          ).map(([label, value, setter]) => (
            <label key={label} className="text-sm">
              {label}{" "}
              <select
                value={value}
                onChange={(event) => setter(event.target.value as AlgorithmName)}
                className="rounded border border-slate-600 bg-slate-800 px-2 py-1"
              >
                {ALGORITHMS.map((algorithm) => (
                  <option key={algorithm} value={algorithm}>
                    {algorithm}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <TopologyCanvas demo={demo} frame={frame} title={primary} />
        <TopologyCanvas demo={demo} frame={comparisonFrame} title={comparison} />
      </div>

      <div className="mt-3">
        <Legend />
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Timeline
            run={primaryRun}
            tick={tick}
            onTick={setTick}
            playing={playing}
            onPlayToggle={() => setPlaying((value) => !value)}
            tickMs={demo.tick_ms}
          />
          <div className="mt-4 grid gap-6 md:grid-cols-2">
            <MetricsPanel run={primaryRun} frame={frame} label={primary} />
            <MetricsPanel run={comparisonRun} frame={comparisonFrame} label={comparison} />
          </div>
        </div>
        <EventLog run={primaryRun} tick={tick} />
      </div>

      {headline && (
        <div className="mt-8 border-t border-slate-700 pt-6">
          <ResultsTable results={headline} />
        </div>
      )}

      <footer className="mt-8 border-t border-slate-800 pt-4 text-xs text-slate-400">
        Every number shown comes from a committed results file. See research/a8-findings.md
        for the hypothesis verdicts, including the ones the data did not support.
      </footer>
    </div>
  );
}
