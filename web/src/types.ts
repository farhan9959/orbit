export type PriorityName = "CRITICAL" | "HIGH" | "NORMAL" | "LOW";

export const PRIORITIES: readonly PriorityName[] = ["CRITICAL", "HIGH", "NORMAL", "LOW"];

export const ALGORITHMS = [
  "spf-static",
  "spf-reconverge",
  "ecmp",
  "cspf",
  "orbit",
] as const;

export type AlgorithmName = (typeof ALGORITHMS)[number];

export interface DemoNode {
  id: string;
  x: number;
  y: number;
}

export interface DemoLink {
  id: string;
  src: number;
  dst: number;
  capacity: number;
}

export interface DemoFlow {
  id: string;
  src: number;
  dst: number;
  demand: number;
  priority: PriorityName;
}

export interface Frame {
  t: number;
  util: number[];
  linkDown: number[];
  nodeDown: number[];
  delivered: Partial<Record<PriorityName, number>>;
  demanded: Partial<Record<PriorityName, number>>;
  blackholed: number;
}

export interface RunEvent {
  t: number;
  type: string;
  payload: Record<string, unknown>;
}

export interface Run {
  frames: Frame[];
  events: RunEvent[];
  eventCount: number;
  controlSeconds: number;
  controlCalls: number;
  pdr: Partial<Record<PriorityName | "OVERALL", number>>;
}

export interface Demo {
  scenario: string;
  tick_ms: number;
  nodes: DemoNode[];
  links: DemoLink[];
  flows: DemoFlow[];
  runs: Record<string, Run>;
}

export interface ResultRow {
  scenario: string;
  family: string;
  failure: string;
  offered_load: number;
  algorithm: string;
  pdr_critical: number | null;
  pdr_high: number | null;
  pdr_normal: number | null;
  pdr_low: number | null;
  pdr: number | null;
  throughput_mbps: number | null;
  control_seconds: number | null;
}

export interface Manifest {
  git_sha: string;
  dirty: boolean;
  python: string;
  platform: string;
  wall_clock_s: number;
}

export interface ResultSet {
  rows: ResultRow[];
  trials: number;
  runs: number;
  manifest?: Manifest;
}

export type Results = Record<string, ResultSet>;
