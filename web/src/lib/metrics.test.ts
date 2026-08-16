import { describe, expect, it } from "vitest";
import {
  bestAndWorst,
  countEvents,
  detectionTick,
  failureTick,
  formatRatio,
  formatSeconds,
  frameRatio,
  overallFrameRatio,
  seriesFor,
} from "./metrics";
import { linkHealth, linkWidth } from "./health";
import type { Frame, Run } from "../types";

const frame: Frame = {
  t: 0,
  util: [0.5],
  linkDown: [0],
  nodeDown: [0],
  delivered: { CRITICAL: 8, LOW: 1 },
  demanded: { CRITICAL: 10, LOW: 4 },
  blackholed: 0,
};

const run: Run = {
  frames: [frame],
  events: [
    { t: 20, type: "FAILURE_INJECTED", payload: {} },
    { t: 23, type: "FAILURE_DETECTED", payload: {} },
    { t: 23, type: "FLOW_REROUTED", payload: {} },
    { t: 24, type: "FLOW_REROUTED", payload: {} },
  ],
  eventCount: 4,
  controlSeconds: 0.5,
  controlCalls: 2,
  pdr: { OVERALL: 0.64 },
};

describe("formatting", () => {
  it("renders an em dash rather than NaN for missing values", () => {
    expect(formatRatio(null)).toBe("—");
    expect(formatRatio(undefined)).toBe("—");
    expect(formatRatio(Number.NaN)).toBe("—");
    expect(formatSeconds(null)).toBe("—");
  });

  it("keeps three decimals on ratios", () => {
    expect(formatRatio(0.5)).toBe("0.500");
    expect(formatRatio(0.123456)).toBe("0.123");
    expect(formatRatio(1)).toBe("1.000");
  });

  it("switches to milliseconds below one second", () => {
    expect(formatSeconds(0.1734)).toBe("173 ms");
    expect(formatSeconds(2.5)).toBe("2.50 s");
  });
});

describe("frame ratios", () => {
  it("computes per-class delivery", () => {
    expect(frameRatio(frame, "CRITICAL")).toBeCloseTo(0.8);
    expect(frameRatio(frame, "LOW")).toBeCloseTo(0.25);
  });

  it("returns null rather than a fabricated ratio when nothing was demanded", () => {
    expect(frameRatio(frame, "HIGH")).toBeNull();
    expect(overallFrameRatio({ ...frame, demanded: {}, delivered: {} })).toBeNull();
  });

  it("weights the overall ratio by demand, not by class count", () => {
    expect(overallFrameRatio(frame)).toBeCloseTo(9 / 14);
  });

  it("builds a series aligned to the frames", () => {
    expect(seriesFor(run, "CRITICAL")).toHaveLength(1);
    expect(seriesFor(run, "OVERALL")[0]).toBeCloseTo(9 / 14);
  });
});

describe("event helpers", () => {
  it("finds the first injection and detection", () => {
    expect(failureTick(run)).toBe(20);
    expect(detectionTick(run)).toBe(23);
  });

  it("shows detection strictly after injection", () => {
    expect(detectionTick(run)! > failureTick(run)!).toBe(true);
  });

  it("counts events by type", () => {
    expect(countEvents(run, "FLOW_REROUTED")).toBe(2);
    expect(countEvents(run, "FLOW_PREEMPTED")).toBe(0);
  });

  it("returns null when a run has no failure", () => {
    expect(failureTick({ ...run, events: [] })).toBeNull();
  });
});

describe("ranking", () => {
  it("picks best and worst, ignoring missing values", () => {
    expect(bestAndWorst({ a: 0.9, b: 0.5, c: null })).toEqual({ best: "a", worst: "b" });
  });

  it("breaks ties deterministically by name", () => {
    expect(bestAndWorst({ b: 0.5, a: 0.5 }).best).toBe("a");
  });

  it("handles an empty set", () => {
    expect(bestAndWorst({})).toEqual({ best: null, worst: null });
  });
});

describe("health encoding", () => {
  it("encodes status by glyph and dash as well as colour", () => {
    const down = linkHealth(0, true);
    const busy = linkHealth(0.8, false);
    expect(down.glyph).not.toBe(busy.glyph);
    expect(down.dash.length).toBeGreaterThan(0);
    expect(down.label).toBe("down");
  });

  it("treats a down link as down regardless of utilisation", () => {
    expect(linkHealth(0.99, true).level).toBe("down");
  });

  it("orders levels by utilisation", () => {
    expect(linkHealth(0.99, false).level).toBe("saturated");
    expect(linkHealth(0.8, false).level).toBe("busy");
    expect(linkHealth(0.3, false).level).toBe("moderate");
    expect(linkHealth(0, false).level).toBe("idle");
  });

  it("clamps width for out-of-range utilisation", () => {
    expect(linkWidth(5, false)).toBe(5);
    expect(linkWidth(-1, false)).toBe(1);
  });
});
