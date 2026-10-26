import { useCallback, useEffect, useRef, useState } from "react";
import {
  type AgentList,
  type AgentResult,
  API_URL,
  api,
  call,
  isFinished,
  type ProgressEvent,
  type QuestionBatch,
  type RunStatus,
  type RunView,
} from "./client";

export interface Loadable<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount, again whenever `key` changes, and on reload(). */
export function useLoad<T>(load: () => Promise<T>, key = ""): Loadable<T> {
  const [state, setState] = useState<{ data?: T; error?: Error; loading: boolean }>({
    loading: true,
  });
  const [tick, setTick] = useState(0);
  const latest = useRef(load);
  latest.current = load;

  // biome-ignore lint/correctness/useExhaustiveDependencies: key and tick are the triggers
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    latest.current().then(
      (data) => live && setState({ data, loading: false }),
      (error: Error) => live && setState({ error, loading: false }),
    );
    return () => {
      live = false;
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, data: state.data, error: state.error, reload };
}

let agentsCache: Promise<AgentList> | undefined;

export function fetchAgents(fresh = false): Promise<AgentList> {
  if (fresh || !agentsCache) {
    agentsCache = call(api.GET("/agents"));
    agentsCache.catch(() => {
      agentsCache = undefined;
    });
  }
  return agentsCache;
}

export function useAgents(): Loadable<AgentList> {
  const first = useRef(true);
  return useLoad(() => {
    const fresh = !first.current;
    first.current = false;
    return fetchAgents(fresh);
  });
}

/** Recent runs, refreshed every few seconds while any of them is still going. */
export function useRuns(limit = 50): Loadable<RunView[]> {
  const runs = useLoad(() => call(api.GET("/runs", { params: { query: { limit } } })), String(limit));
  const active = runs.data?.some((r) => !isFinished(r.status)) ?? false;
  const { reload } = runs;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(reload, 2500);
    return () => clearInterval(timer);
  }, [active, reload]);
  return runs;
}

export interface LiveRun {
  run: RunView | undefined;
  /** Every progress event received, oldest first. */
  timeline: ProgressEvent[];
  error: Error | undefined;
  /** The run is gone (expired or never existed). */
  missing: boolean;
}

/**
 * Follow one run: load it, then listen to its server-sent events until the result.
 * The browser's EventSource resends Last-Event-ID on reconnect, so nothing is missed.
 */
export function useLiveRun(runId: string): LiveRun {
  const [run, setRun] = useState<RunView>();
  const [timeline, setTimeline] = useState<ProgressEvent[]>([]);
  const [error, setError] = useState<Error>();
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    let source: EventSource | undefined;
    let poll: ReturnType<typeof setInterval> | undefined;
    setRun(undefined);
    setTimeline([]);
    setError(undefined);
    setMissing(false);

    const refresh = () =>
      call(api.GET("/runs/{run_id}", { params: { path: { run_id: runId } } })).then(
        (view) => {
          if (!live) return view;
          setRun(view);
          return view;
        },
        (err: Error & { status?: number }) => {
          if (!live) return undefined;
          if (err.status === 404) setMissing(true);
          else setError(err);
          return undefined;
        },
      );

    const stop = () => {
      source?.close();
      if (poll) clearInterval(poll);
      poll = undefined;
    };

    // queue positions are not pushed as events, so poll while waiting in line
    const pollWhileQueued = () => {
      if (poll) return;
      poll = setInterval(() => {
        refresh().then((v) => {
          if (v && v.status !== "queued" && poll) {
            clearInterval(poll);
            poll = undefined;
          }
        });
      }, 2000);
    };

    refresh().then((view) => {
      if (!live || !view) return;
      // A finished run's stream replays its buffered events and ends, which fills in the
      // stage history; a live one keeps streaming until the result. The view already
      // includes every event up to `last_event`, so replayed ones only add to the timeline.
      const seen = view.last_event ?? 0;
      const isNew = (e: Event) => Number((e as MessageEvent).lastEventId) > seen;
      source = new EventSource(`${API_URL}/runs/${encodeURIComponent(runId)}/events`);
      if (view.status === "queued") pollWhileQueued();
      source.addEventListener("status", (e) => {
        if (!isNew(e)) return;
        const { status } = JSON.parse((e as MessageEvent).data) as { status: RunStatus };
        if (status === "queued") pollWhileQueued();
        setRun((r) =>
          r
            ? {
                ...r,
                status,
                queue_position: status === "queued" ? r.queue_position : null,
                question: status === "waiting" ? r.question : null,
              }
            : r,
        );
      });
      source.addEventListener("question", (e) => {
        if (!isNew(e)) return;
        const question = JSON.parse((e as MessageEvent).data) as QuestionBatch;
        setRun((r) => (r ? { ...r, status: "waiting", question } : r));
      });
      source.addEventListener("progress", (e) => {
        const event = JSON.parse((e as MessageEvent).data) as ProgressEvent;
        setTimeline((t) => [...t, event]);
        setRun((r) => (r ? { ...r, progress: event } : r));
      });
      source.addEventListener("result", (e) => {
        const { status, result } = JSON.parse((e as MessageEvent).data) as {
          status: RunStatus;
          result: AgentResult | null;
        };
        stop();
        setRun((r) => (r ? { ...r, status, result } : r));
        refresh(); // picks up finished_at and the final view
      });
      source.onerror = () => {
        // EventSource retries on its own; check the run still exists so we don't retry forever
        refresh().then((v) => {
          if (!v || isFinished(v.status)) stop();
        });
      };
    });

    return () => {
      live = false;
      stop();
    };
  }, [runId]);

  return { run, timeline, error, missing };
}
