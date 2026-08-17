import { describe, expect, it } from "vitest";
import {
  appendEvents,
  circleLayout,
  classify,
  deltaToFrame,
  snapshotToDemo,
  type LiveDelta,
  type LiveSnapshot,
} from "./live";

const SNAPSHOT: LiveSnapshot = {
  type: "snapshot",
  tick: 4,
  algorithm: "orbit",
  nodes: ["n000", "n001", "n002"],
  links: [
    { id: "n000>n001", src: "n000", dst: "n001" },
    { id: "n001>n002", src: "n001", dst: "n002" },
  ],
};

const DELTA: LiveDelta = {
  tick: 5,
  time_s: 0.5,
  delivered: { CRITICAL: 10 },
  demanded: { CRITICAL: 20 },
  blackholed: 1,
  util: [0.5, 0.25],
  linkDown: [0, 1],
  nodeDown: [0, 0, 1],
  cascadeDepth: 2,
  events: [],
};

describe("circleLayout", () => {
  it("places every node and keeps them distinct", () => {
    const laid = circleLayout(SNAPSHOT.nodes);
    expect(laid).toHaveLength(3);
    expect(new Set(laid.map((n) => `${n.x.toFixed(4)},${n.y.toFixed(4)}`)).size).toBe(3);
  });

  it("is stable across calls so a reconnect does not move the graph", () => {
    expect(circleLayout(SNAPSHOT.nodes)).toEqual(circleLayout(SNAPSHOT.nodes));
  });

  it("does not divide by zero on an empty topology", () => {
    expect(circleLayout([])).toEqual([]);
  });
});

describe("snapshotToDemo", () => {
  it("resolves link endpoints from node ids to the indices the canvas expects", () => {
    const demo = snapshotToDemo(SNAPSHOT);
    expect(demo.links.map((l) => [l.src, l.dst])).toEqual([
      [0, 1],
      [1, 2],
    ]);
  });

  it("names the scenario after the running controller", () => {
    expect(snapshotToDemo(SNAPSHOT).scenario).toContain("orbit");
  });
});

describe("deltaToFrame", () => {
  it("carries the positional arrays through unchanged", () => {
    const frame = deltaToFrame(DELTA);
    expect(frame.t).toBe(5);
    expect(frame.util).toEqual([0.5, 0.25]);
    expect(frame.linkDown).toEqual([0, 1]);
    expect(frame.nodeDown).toEqual([0, 0, 1]);
    expect(frame.blackholed).toBe(1);
  });

  it("produces arrays the snapshot can index", () => {
    const demo = snapshotToDemo(SNAPSHOT);
    const frame = deltaToFrame(DELTA);
    expect(frame.util).toHaveLength(demo.links.length);
    expect(frame.nodeDown).toHaveLength(demo.nodes.length);
  });
});

describe("classify", () => {
  it("recognises a snapshot", () => {
    expect(classify(SNAPSHOT)).toBe(SNAPSHOT);
  });

  it("recognises a delta by its positional arrays", () => {
    expect(classify(DELTA)).toBe(DELTA);
  });

  it("rejects anything else rather than guessing", () => {
    expect(classify(null)).toBeNull();
    expect(classify("delta")).toBeNull();
    expect(classify({ type: "snapshot" })).toBeNull();
    expect(classify({ tick: 3 })).toBeNull();
  });
});

describe("appendEvents", () => {
  it("keeps the newest entries when the log overflows", () => {
    const kept = appendEvents([1, 2, 3], [4, 5], 3);
    expect(kept).toEqual([3, 4, 5]);
  });

  it("leaves a short log alone", () => {
    expect(appendEvents([1], [2], 10)).toEqual([1, 2]);
  });
});
