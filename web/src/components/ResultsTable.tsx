import { useMemo, useState } from "react";
import type { ResultSet } from "../types";
import { formatRatio } from "../lib/metrics";
import { bestAndWorst } from "../lib/metrics";
import { ALGORITHMS } from "../types";

const METRICS = [
  { key: "pdr_critical", label: "CRITICAL PDR" },
  { key: "pdr_high", label: "HIGH PDR" },
  { key: "pdr_low", label: "LOW PDR" },
  { key: "pdr", label: "Overall PDR" },
] as const;

export function ResultsTable({ results }: { results: ResultSet }) {
  const [metric, setMetric] = useState<(typeof METRICS)[number]["key"]>("pdr_critical");

  const byFailure = useMemo(() => {
    const grouped = new Map<string, Record<string, number | null>>();
    for (const row of results.rows) {
      const bucket = grouped.get(row.failure) ?? {};
      const value = row[metric];
      const existing = bucket[row.algorithm];
      bucket[row.algorithm] =
        existing === undefined || existing === null
          ? value
          : value === null
            ? existing
            : (existing + value) / 2;
      grouped.set(row.failure, bucket);
    }
    return [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [results.rows, metric]);

  return (
    <section aria-labelledby="results-heading">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="results-heading" className="text-lg font-semibold">
          A8 benchmark — median across {results.trials} paired trials
        </h2>
        <label className="text-sm">
          Metric{" "}
          <select
            value={metric}
            onChange={(event) => setMetric(event.target.value as typeof metric)}
            className="rounded border border-slate-600 bg-slate-800 px-2 py-1"
          >
            {METRICS.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">
            Median {metric} by failure scenario and algorithm, pooled over topology families,
            {results.runs} runs total
          </caption>
          <thead>
            <tr className="text-left">
              <th scope="col" className="border-b border-slate-600 py-2 pr-3">
                Failure scenario
              </th>
              {ALGORITHMS.map((algorithm) => (
                <th key={algorithm} scope="col" className="border-b border-slate-600 py-2 pr-3">
                  {algorithm}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {byFailure.map(([failure, values]) => {
              const { best, worst } = bestAndWorst(values);
              return (
                <tr key={failure} className="border-b border-slate-800">
                  <th scope="row" className="py-1.5 pr-3 font-normal">
                    {failure}
                  </th>
                  {ALGORITHMS.map((algorithm) => {
                    const value = values[algorithm] ?? null;
                    const isBest = algorithm === best;
                    const isWorst = algorithm === worst;
                    return (
                      <td key={algorithm} className="py-1.5 pr-3 tabular-nums">
                        <span className={isBest ? "font-bold underline" : ""}>
                          {formatRatio(value)}
                        </span>
                        {isBest && <span className="ml-1 text-xs text-emerald-300">▲ best</span>}
                        {isWorst && <span className="ml-1 text-xs text-red-300">▼ worst</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {results.manifest && (
        <p className="mt-2 text-xs text-slate-400">
          Source: commit <code>{results.manifest.git_sha.slice(0, 10)}</code>, Python{" "}
          {results.manifest.python}, {results.runs} runs,{" "}
          {results.manifest.dirty ? (
            <strong className="text-red-300">dirty working tree — not reportable</strong>
          ) : (
            "clean working tree"
          )}
          .
        </p>
      )}
    </section>
  );
}
