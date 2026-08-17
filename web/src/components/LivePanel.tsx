import { useCallback, useEffect, useRef, useState } from "react";
import type { Demo, Frame } from "../types";
import { ALGORITHMS } from "../types";
import { TopologyCanvas } from "./TopologyCanvas";
import { MetricsPanel } from "./MetricsPanel";
import {
  INJECTION_KINDS,
  classify,
  control,
  createSession,
  deltaToFrame,
  inject,
  login,
  snapshotToDemo,
  switchAlgorithm,
  type InjectionKind,
  type LiveState,
} from "../lib/live";

const EMPTY_FRAME: Frame = {
  t: 0,
  util: [],
  linkDown: [],
  nodeDown: [],
  delivered: {},
  demanded: {},
  blackholed: 0,
};

/**
 * A live session driven by the API, as opposed to the replay of a committed run.
 *
 * Nothing shown here is a published result: it is one unseeded 30-node session running in
 * the server's memory. The replay view remains the only thing tied to the results files.
 */
export function LivePanel() {
  const [csrf, setCsrf] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState<LiveState | null>(null);
  const [demo, setDemo] = useState<Demo | null>(null);
  const [frame, setFrame] = useState<Frame>(EMPTY_FRAME);
  const [cascade, setCascade] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const source = useRef<EventSource | null>(null);

  useEffect(() => () => source.current?.close(), []);

  const note = useCallback((message: string) => {
    setLog((entries) => [message, ...entries].slice(0, 12));
  }, []);

  const guard = useCallback(
    async (what: string, action: () => Promise<LiveState>) => {
      try {
        setState(await action());
        setError(null);
        note(what);
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    },
    [note],
  );

  async function connect(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const token = await login(String(form.get("email")), String(form.get("password")));
      const id = await createSession(token, {
        nodes: 30,
        flows: 60,
        algorithm: "orbit",
        failure: "none",
      });
      setCsrf(token);
      setSessionId(id);
      setError(null);
      note(`session ${id.slice(0, 8)} started`);

      const stream = new EventSource(`/api/v1/sessions/${id}/stream`, { withCredentials: true });
      stream.onmessage = (message) => {
        const payload = classify(JSON.parse(message.data));
        if (payload === null) return;
        if ("nodes" in payload) {
          setDemo(snapshotToDemo(payload));
        } else {
          setFrame(deltaToFrame(payload));
          setCascade(payload.cascadeDepth);
        }
      };
      stream.onerror = () => setError("stream disconnected");
      source.current = stream;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  if (sessionId === null || csrf === null) {
    return (
      <section aria-labelledby="live-heading" className="max-w-md">
        <h2 id="live-heading" className="mb-2 text-lg font-semibold">
          Live session
        </h2>
        <p className="mb-3 text-sm text-slate-300">
          Runs a simulation in the API and streams it here. Requires an account on this
          server; nothing shown in live mode is a published result.
        </p>
        <form onSubmit={connect} className="space-y-2 text-sm">
          <label className="block">
            Email
            <input
              name="email"
              type="email"
              required
              autoComplete="username"
              className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-2 py-1"
            />
          </label>
          <label className="block">
            Password
            <input
              name="password"
              type="password"
              required
              autoComplete="current-password"
              className="mt-1 w-full rounded border border-slate-600 bg-slate-800 px-2 py-1"
            />
          </label>
          <button
            type="submit"
            className="rounded border border-slate-500 bg-slate-700 px-3 py-1 font-medium"
          >
            Start a live session
          </button>
        </form>
        {error && (
          <p role="alert" className="mt-3 text-sm text-red-300">
            {error}
          </p>
        )}
      </section>
    );
  }

  return (
    <section aria-labelledby="live-heading" className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="live-heading" className="text-lg font-semibold">
          Live session{" "}
          <span className="text-sm font-normal text-slate-300">
            tick {state?.tick ?? frame.t} · {state?.running ? "running" : "paused"} ·{" "}
            {state?.algorithm ?? "orbit"} · cascade depth {cascade}
          </span>
        </h2>
        <p className="text-xs text-amber-200">Not a published result — one unseeded session.</p>
      </div>

      <div className="flex flex-wrap gap-4">
        <fieldset className="rounded border border-slate-700 px-3 py-2">
          <legend className="px-1 text-xs text-slate-300">Transport</legend>
          <div className="flex gap-2">
            {(["start", "pause", "step", "reset"] as const).map((action) => (
              <button
                key={action}
                type="button"
                onClick={() => guard(action, () => control(sessionId, action, csrf))}
                className="rounded border border-slate-500 bg-slate-700 px-2 py-1 text-sm"
              >
                {action}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="rounded border border-slate-700 px-3 py-2">
          <legend className="px-1 text-xs text-slate-300">Inject a failure</legend>
          <div className="flex flex-wrap gap-2">
            {INJECTION_KINDS.map((kind: InjectionKind) => (
              <button
                key={kind}
                type="button"
                onClick={() => guard(`injected ${kind}`, () => inject(sessionId, kind, csrf))}
                className="rounded border border-amber-500/60 bg-slate-700 px-2 py-1 text-sm"
              >
                {kind.replace(/_/g, " ")}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset className="rounded border border-slate-700 px-3 py-2">
          <legend className="px-1 text-xs text-slate-300">Controller</legend>
          <label className="text-sm">
            <span className="sr-only">Switch algorithm</span>
            <select
              value={state?.algorithm ?? "orbit"}
              onChange={(event) =>
                guard(`switched to ${event.target.value}`, () =>
                  switchAlgorithm(sessionId, event.target.value, csrf),
                )
              }
              className="rounded border border-slate-600 bg-slate-800 px-2 py-1"
            >
              {ALGORITHMS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </fieldset>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {demo ? (
          <TopologyCanvas demo={demo} frame={frame} title={state?.algorithm ?? "live"} />
        ) : (
          <p aria-live="polite" className="text-sm text-slate-300">
            Waiting for the first snapshot…
          </p>
        )}
        <div className="space-y-3">
          <MetricsPanel
            run={{
              frames: [],
              events: [],
              eventCount: 0,
              controlSeconds: 0,
              controlCalls: 0,
              pdr: {},
            }}
            frame={frame}
            label="live"
          />
          <section aria-labelledby="live-log" className="text-sm">
            <h3 id="live-log" className="mb-1 font-semibold">
              Actions
            </h3>
            <ol
              className="max-h-40 overflow-y-auto rounded border border-slate-700 bg-slate-950 p-2 text-xs focus:outline focus:outline-2 focus:outline-sky-400"
              aria-live="polite"
              aria-label="Recent live-session actions, scrollable"
              tabIndex={0}
            >
              {log.length === 0 && <li className="text-slate-400">Nothing yet.</li>}
              {log.map((entry, index) => (
                <li key={`${entry}-${index}`}>{entry}</li>
              ))}
            </ol>
          </section>
        </div>
      </div>
    </section>
  );
}
