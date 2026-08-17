/**
 * Client for the live-session API (F29, F30).
 *
 * Everything here is a pure function over wire payloads so it can be tested without a
 * browser, a server or a fake EventSource. The component owns the socket; this file owns
 * the meaning of what comes down it.
 */
import type { Demo, DemoNode, Frame, PriorityName } from "../types";

export interface LiveSnapshot {
  type: "snapshot";
  tick: number;
  algorithm: string;
  nodes: string[];
  links: { id: string; src: string; dst: string }[];
}

export interface LiveDelta {
  type?: "delta";
  tick: number;
  time_s: number;
  delivered: Partial<Record<PriorityName, number>>;
  demanded: Partial<Record<PriorityName, number>>;
  blackholed: number;
  util: number[];
  linkDown: number[];
  nodeDown: number[];
  cascadeDepth: number;
  events: { type: string; payload: Record<string, unknown> }[];
}

export interface LiveState {
  tick: number;
  running: boolean;
  algorithm: string;
  injections: number;
}

export const INJECTION_KINDS = [
  "critical_link",
  "random_link",
  "random_node",
  "srlg",
  "surge",
] as const;

export type InjectionKind = (typeof INJECTION_KINDS)[number];

/**
 * Lay the snapshot's nodes on a circle.
 *
 * The server sends topology without coordinates, and it should: coordinates are a viewing
 * concern, and a spring layout of a live graph would move every node on every reconnect.
 * A circle keyed by index is stable across reconnects and legible to the 100-node session
 * cap, which is all a live view needs.
 */
export function circleLayout(nodes: string[]): DemoNode[] {
  return nodes.map((id, index) => {
    const angle = (2 * Math.PI * index) / Math.max(1, nodes.length);
    return { id, x: Math.cos(angle), y: Math.sin(angle) };
  });
}

/** Reshape a snapshot into the same structure the replay viewer draws. */
export function snapshotToDemo(snapshot: LiveSnapshot): Demo {
  const index = new Map(snapshot.nodes.map((id, position) => [id, position]));
  return {
    scenario: `live · ${snapshot.algorithm}`,
    tick_ms: 100,
    nodes: circleLayout(snapshot.nodes),
    links: snapshot.links.map((link) => ({
      id: link.id,
      src: index.get(link.src) ?? 0,
      dst: index.get(link.dst) ?? 0,
      capacity: 0,
    })),
    flows: [],
    runs: {},
  };
}

/** A delta is already positional against the snapshot, so this is a rename, not a transform. */
export function deltaToFrame(delta: LiveDelta): Frame {
  return {
    t: delta.tick,
    util: delta.util,
    linkDown: delta.linkDown,
    nodeDown: delta.nodeDown,
    delivered: delta.delivered,
    demanded: delta.demanded,
    blackholed: delta.blackholed,
  };
}

/**
 * Decide what an SSE payload is.
 *
 * The server tags snapshots and deltas, but a reconnecting client can see either first, so
 * the caller must branch rather than assume ordering.
 */
export function classify(payload: unknown): LiveSnapshot | LiveDelta | null {
  if (typeof payload !== "object" || payload === null) return null;
  const candidate = payload as { type?: string; nodes?: unknown; util?: unknown };
  if (candidate.type === "snapshot" && Array.isArray(candidate.nodes)) {
    return payload as LiveSnapshot;
  }
  if (Array.isArray(candidate.util)) return payload as LiveDelta;
  return null;
}

/**
 * Keep a bounded tail of events, newest last.
 *
 * A live session runs indefinitely, so an unbounded log is a memory leak with a scrollbar.
 */
export function appendEvents<T>(existing: T[], incoming: T[], limit = 200): T[] {
  const merged = [...existing, ...incoming];
  return merged.length <= limit ? merged : merged.slice(merged.length - limit);
}

async function send(path: string, body: unknown, csrf: string): Promise<Response> {
  return fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(body),
  });
}

export async function login(email: string, password: string): Promise<string> {
  const response = await fetch("/api/v1/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(`login failed (${response.status})`);
  return (await response.json()).csrf_token as string;
}

export async function createSession(
  csrf: string,
  options: { nodes: number; flows: number; algorithm: string; failure: string },
): Promise<string> {
  const response = await send("/api/v1/sessions", options, csrf);
  if (!response.ok) throw new Error(`could not start a session (${response.status})`);
  return (await response.json()).id as string;
}

export const control = (id: string, action: string, csrf: string) =>
  send(`/api/v1/sessions/${id}/control`, { action }, csrf).then(asState);

export const inject = (id: string, kind: InjectionKind, csrf: string) =>
  send(`/api/v1/sessions/${id}/inject`, { kind }, csrf).then(asState);

export const switchAlgorithm = (id: string, algorithm: string, csrf: string) =>
  send(`/api/v1/sessions/${id}/algorithm`, { algorithm }, csrf).then(asState);

async function asState(response: Response): Promise<LiveState> {
  if (!response.ok) throw new Error(`request failed (${response.status})`);
  return (await response.json()) as LiveState;
}
