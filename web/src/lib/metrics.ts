import type { Frame, PriorityName, Run } from "../types";
import { PRIORITIES } from "../types";

export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(3);
}

export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 1) return `${(value * 1000).toFixed(0)} ms`;
  return `${value.toFixed(2)} s`;
}

export function frameRatio(frame: Frame, priority: PriorityName): number | null {
  const demanded = frame.demanded[priority];
  const delivered = frame.delivered[priority];
  if (demanded === undefined || demanded <= 0) return null;
  return (delivered ?? 0) / demanded;
}

export function overallFrameRatio(frame: Frame): number | null {
  let delivered = 0;
  let demanded = 0;
  for (const priority of PRIORITIES) {
    delivered += frame.delivered[priority] ?? 0;
    demanded += frame.demanded[priority] ?? 0;
  }
  return demanded > 0 ? delivered / demanded : null;
}

export function seriesFor(run: Run, priority: PriorityName | "OVERALL"): (number | null)[] {
  return run.frames.map((frame) =>
    priority === "OVERALL" ? overallFrameRatio(frame) : frameRatio(frame, priority),
  );
}

export function failureTick(run: Run): number | null {
  const injected = run.events.find((event) => event.type === "FAILURE_INJECTED");
  return injected ? injected.t : null;
}

export function detectionTick(run: Run): number | null {
  const detected = run.events.find((event) => event.type === "FAILURE_DETECTED");
  return detected ? detected.t : null;
}

export function countEvents(run: Run, type: string): number {
  return run.events.filter((event) => event.type === type).length;
}

export function bestAndWorst(
  values: Record<string, number | null | undefined>,
): { best: string | null; worst: string | null } {
  const entries = Object.entries(values).filter(
    (entry): entry is [string, number] => typeof entry[1] === "number" && !Number.isNaN(entry[1]),
  );
  if (entries.length === 0) return { best: null, worst: null };
  const sorted = [...entries].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  return { best: sorted[0][0], worst: sorted[sorted.length - 1][0] };
}
