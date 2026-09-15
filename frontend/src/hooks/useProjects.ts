import { useCallback, useEffect, useRef, useState } from "react";
import { api, CanopyApiError } from "@/api/client";
import type { JobResult, JobStatus, Project, Run } from "@/types";

type ErrorInfo = { code: string; message: string };

const toError = (err: unknown): ErrorInfo =>
  err instanceof CanopyApiError ? { code: err.code, message: err.message } : { code: "unknown", message: "Something unexpected happened. Please try again." };

const POLL_MS = 1500;

/** The project list. Polls gently while any project has a run in flight so cards update on their own. */
export function useProjects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<ErrorInfo | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProjects(await api.projects());
      setError(null);
    } catch (err) {
      setError(toError(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = projects?.some((p) => p.latest_run && (p.latest_run.status === "queued" || p.latest_run.status === "running"));
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, POLL_MS * 2);
    return () => clearInterval(t);
  }, [busy, refresh]);

  return { projects, error, refresh, setProjects };
}

interface RunData {
  result: JobResult;
  crowns: GeoJSON.FeatureCollection;
  rejected: GeoJSON.FeatureCollection;
}

// Results of finished runs never change, so they are cached for the session.
const runCache = new Map<string, Promise<RunData>>();

function loadRun(runId: string): Promise<RunData> {
  let p = runCache.get(runId);
  if (!p) {
    p = (async () => {
      const result = await api.result(runId);
      const [crowns, rejected] = await Promise.all([api.crowns(result), api.rejected(result)]);
      return { result, crowns, rejected };
    })();
    p.catch(() => runCache.delete(runId));
    runCache.set(runId, p);
  }
  return p;
}

/**
 * One project: its runs, the run being viewed, that run's full result, and live stage progress of any
 * run in flight. When a new run finishes it becomes the viewed run unless the user picked another.
 */
export function useProject(projectId: string, requestedRunId?: string) {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [data, setData] = useState<(RunData & { runId: string }) | null>(null);
  const [loadingRun, setLoadingRun] = useState(false);
  const [liveStatus, setLiveStatus] = useState<JobStatus | null>(null);
  const [runError, setRunError] = useState<ErrorInfo | null>(null);
  const followLatest = useRef(!requestedRunId);

  const refresh = useCallback(async () => {
    try {
      const p = await api.project(projectId);
      setProject(p);
      setError(null);
      return p;
    } catch (err) {
      setError(toError(err));
      return null;
    }
  }, [projectId]);

  useEffect(() => {
    setProject(null);
    setData(null);
    setLiveStatus(null);
    followLatest.current = !requestedRunId;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the project changes
  }, [projectId, refresh]);

  const runs = project?.runs ?? [];
  const activeRun: Run | null =
    (requestedRunId && runs.find((r) => r.id === requestedRunId)) ||
    (project?.latest_succeeded_run_id ? runs.find((r) => r.id === project.latest_succeeded_run_id) ?? null : null);
  const inFlight = runs.find((r) => r.status === "queued" || r.status === "running") ?? null;

  // Load the viewed run's result.
  useEffect(() => {
    if (!activeRun || activeRun.status !== "succeeded") return;
    if (data?.runId === activeRun.id) return;
    let alive = true;
    setLoadingRun(true);
    loadRun(activeRun.id)
      .then((d) => alive && setData({ ...d, runId: activeRun.id }))
      .catch((err) => alive && setRunError(toError(err)))
      .finally(() => alive && setLoadingRun(false));
    return () => {
      alive = false;
    };
  }, [activeRun?.id, activeRun?.status, data?.runId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll the run in flight for named stages; refresh the project when it lands.
  useEffect(() => {
    if (!inFlight) {
      setLiveStatus(null);
      return;
    }
    let alive = true;
    const tick = async () => {
      try {
        const s = await api.status(inFlight.id);
        if (!alive) return;
        setLiveStatus(s);
        if (s.status === "succeeded" || s.status === "failed") {
          const p = await refresh();
          if (s.status === "failed") setRunError({ code: s.error_code ?? "failed", message: s.error_message ?? "The analysis failed." });
          if (p && s.status === "succeeded" && followLatest.current) setData(null);
          return;
        }
      } catch {
        /* transient; keep polling */
      }
      if (alive) timer = setTimeout(tick, POLL_MS);
    };
    let timer = setTimeout(tick, 300);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [inFlight?.id, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  const startRun = useCallback(
    async (params: Parameters<typeof api.startRun>[1]) => {
      try {
        setRunError(null);
        followLatest.current = true;
        await api.startRun(projectId, params);
        await refresh();
      } catch (err) {
        setRunError(toError(err));
      }
    },
    [projectId, refresh],
  );

  const dataForActive = data && activeRun && data.runId === activeRun.id ? data : null;

  return {
    project,
    error,
    runs,
    activeRun,
    inFlight,
    liveStatus,
    result: dataForActive?.result ?? null,
    crowns: dataForActive?.crowns ?? null,
    rejected: dataForActive?.rejected ?? null,
    loadingRun: loadingRun || (!!activeRun && !dataForActive),
    runError,
    dismissRunError: () => setRunError(null),
    startRun,
    refresh,
    setProject,
  };
}
