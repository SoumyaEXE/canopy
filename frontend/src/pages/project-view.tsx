import { useCallback, useEffect, useRef, useState } from "react";
import {
  RiArrowDownSLine,
  RiArrowLeftSLine,
  RiCheckboxMultipleLine,
  RiDashboardLine,
  RiErrorWarningLine,
  RiFlowChart,
  RiFolderLine,
  RiHistoryLine,
  RiLayoutLeftLine,
  RiLayoutRightLine,
  RiMap2Line,
  RiPlantLine,
  RiPlayFill,
  RiShieldCheckLine,
} from "@remixicon/react";
import { api, CanopyApiError } from "@/api/client";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { IconButton } from "@/components/base/buttons/icon-button";
import { Dropdown, DropdownItem, DropdownPopover, DropdownTrigger } from "@/components/base/dropdown/dropdown";
import { Tab, TabList, TabPanel, Tabs } from "@/components/base/tabs/tabs";
import { AiPanel, AskAiButton } from "@/components/canopy/ai-panel";
import { MapErrorBoundary } from "@/components/canopy/map-error-boundary";
import { MapView, type LayerVisibility, type MapMode } from "@/components/canopy/map-view";
import { ProgressOverlay } from "@/components/canopy/progress-overlay";
import { Shell, TopBar, useMedia } from "@/components/canopy/shell";
import type { NavGroup } from "@/components/canopy/sidebar";
import { EmptyState, Panel, Skeleton, SOURCE_LABEL, formatRelative } from "@/components/canopy/ui";
import { MIN_CLICKS, ValidationPanel } from "@/components/canopy/validation-panel";
import { MapLegend, ParametersPanel, ResultsSummary, StylePanel, countChanges, type MapStyleState } from "@/components/canopy/workspace-panels";
import { prefetchRun, useProject } from "@/hooks/useProjects";
import type { ProjectTab, Route } from "@/lib/router";
import { AuditPage } from "@/pages/audit";
import { CrownsPage } from "@/pages/crowns";
import { OverviewPage } from "@/pages/overview";
import { PipelinePage } from "@/pages/pipeline";
import { RunsPage } from "@/pages/runs";
import type { JobParams, ValidationResult } from "@/types";
import { cx } from "@/utils/cx";

type LngLat = [number, number];
type NavKey = ProjectTab | "projects" | "limitations";

const DEFAULT_PARAMS: JobParams = {
  detector: "classical",
  yolo_variant: "yolo11s-seg",
  min_crown_diameter_m: 3,
  veg_index: "exg",
  threshold_mode: "otsu",
  threshold_manual: null,
  tile_zoom: 18,
  acquisition_datetime_utc: null,
  enable_height: true,
  image_m_per_px: null,
};

const TAB_META: Record<ProjectTab, string> = {
  overview: "Overview",
  map: "Map",
  crowns: "Crowns",
  pipeline: "Pipeline",
  validation: "Validation",
  runs: "Runs",
  audit: "Audit",
};

const RERUN_DEBOUNCE_MS = 900;

function TableSkeleton() {
  return (
    <Panel className="gap-3">
      <Skeleton className="h-8 w-80" />
      {Array.from({ length: 10 }, (_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </Panel>
  );
}

export function ProjectView({
  projectId,
  tab,
  runId,
  navigate,
  notify,
}: {
  projectId: string;
  tab: ProjectTab;
  runId?: string;
  navigate: (r: Route, opts?: { replace?: boolean }) => void;
  notify: (title: string, message: string) => void;
}) {
  const p = useProject(projectId, runId);
  const project = p.project;
  const isDesktop = useMedia("(min-width: 1024px)");
  const isPhone = !useMedia("(min-width: 768px)");

  const [params, setParams] = useState<JobParams>(DEFAULT_PARAMS);
  const [autoRun, setAutoRun] = useState(true);
  const [style, setStyle] = useState<MapStyleState>({ basemap: "auto", colorBy: "confidence", palette: "viridis", fillOpacity: 45 });
  const [layers, setLayers] = useState<LayerVisibility>({ imagery: true, canopy: true, crowns: true, rejected: false });
  const [imageryOpacity, setImageryOpacity] = useState(85);
  const [focus, setFocus] = useState<{ lngLat: LngLat; crownId?: number; nonce: number } | null>(null);
  const [showLeft, setShowLeft] = useState(true);
  const [showRight, setShowRight] = useState(true);
  const [inspectorTab, setInspectorTab] = useState<"results" | "style">("results");
  const [aiOpen, setAiOpen] = useState(false);

  // Ctrl/Cmd + I toggles Canopy AI from anywhere in the workspace.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "i") {
        e.preventDefault();
        setAiOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const [vCorner, setVCorner] = useState<LngLat | null>(null);
  const [vBbox, setVBbox] = useState<[number, number, number, number] | null>(null);
  const [vClicks, setVClicks] = useState<LngLat[]>([]);
  const [vResult, setVResult] = useState<ValidationResult | null>(null);
  const [vSubmitting, setVSubmitting] = useState(false);

  // Parameters start from the viewed run (or the project's last-used set) whenever the viewed run changes.
  const seededFor = useRef<string | null>(null);
  useEffect(() => {
    const key = p.activeRun?.id ?? project?.id ?? null;
    if (!key || seededFor.current === key) return;
    seededFor.current = key;
    setParams({ ...DEFAULT_PARAMS, ...(p.activeRun?.params ?? project?.params ?? {}) });
  }, [p.activeRun?.id, project?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (p.runError) notify("Run failed", p.runError.message);
  }, [p.runError]); // eslint-disable-line react-hooks/exhaustive-deps

  const resetValidation = useCallback(() => {
    setVCorner(null);
    setVBbox(null);
    setVClicks([]);
    setVResult(null);
  }, []);

  const go = (next: NavKey) => {
    if (next === "projects") return navigate({ name: "projects" });
    if (next === "limitations") return navigate({ name: "limitations" });
    if (tab === "validation" && next !== "validation") resetValidation();
    navigate({ name: "project", id: projectId, tab: next, run: runId });
  };

  // ---- runs ----------------------------------------------------------------------------------------
  const running = !!p.inFlight;
  const run = useCallback(
    async (next: JobParams) => {
      if (runId) navigate({ name: "project", id: projectId, tab, run: undefined }, { replace: true });
      await p.startRun(next);
    },
    [p, runId, projectId, tab, navigate],
  );

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const updateParams = (next: JobParams) => {
    setParams(next);
    if (timer.current) clearTimeout(timer.current);
    if (!autoRun) return;
    timer.current = setTimeout(() => {
      if (countChanges(next, p.activeRun?.params) > 0) void run(next);
    }, RERUN_DEBOUNCE_MS);
  };
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  // ---- validation ------------------------------------------------------------------------------------
  const validating = tab === "validation";
  const vStep: "rect" | "click" | "done" = !vBbox ? "rect" : vResult?.ok ? "done" : "click";
  const mapMode: MapMode = validating ? (vStep === "rect" ? "validate-rect" : vStep === "click" ? "validate-click" : "idle") : "idle";

  const onMapClick = (pt: LngLat) => {
    if (!validating) return;
    if (vStep === "rect") {
      if (!vCorner) setVCorner(pt);
      else {
        const bbox: [number, number, number, number] = [Math.min(vCorner[0], pt[0]), Math.min(vCorner[1], pt[1]), Math.max(vCorner[0], pt[0]), Math.max(vCorner[1], pt[1])];
        if (bbox[2] - bbox[0] < 0.00001 || bbox[3] - bbox[1] < 0.00001) return;
        setVBbox(bbox);
        setVCorner(null);
      }
    } else if (vStep === "click" && vBbox && pt[0] >= vBbox[0] && pt[0] <= vBbox[2] && pt[1] >= vBbox[1] && pt[1] <= vBbox[3]) {
      setVClicks((c) => [...c, pt]);
    }
  };

  const submitValidation = async () => {
    if (!p.activeRun || !vBbox || vClicks.length < MIN_CLICKS) return;
    setVSubmitting(true);
    try {
      setVResult(await api.validate(p.activeRun.id, vBbox, vClicks));
    } catch (err) {
      notify("Validation failed", err instanceof CanopyApiError ? err.message : "Something unexpected happened.");
    } finally {
      setVSubmitting(false);
    }
  };

  // ---- navigation ------------------------------------------------------------------------------------
  const groups: NavGroup<NavKey>[] = [
    { label: "Workspace", entries: [{ key: "projects", label: "All projects", icon: RiFolderLine }] },
    {
      label: project?.name ?? "Project",
      entries: [
        { key: "overview", label: "Overview", icon: RiDashboardLine, badge: p.result?.warnings.length || undefined, alert: !!p.result?.warnings.length },
        { key: "map", label: "Map", icon: RiMap2Line },
        { key: "crowns", label: "Crowns", icon: RiPlantLine, badge: p.result?.summary.crown_count },
        { key: "pipeline", label: "Pipeline", icon: RiFlowChart },
        { key: "validation", label: "Validation", icon: RiCheckboxMultipleLine },
        { key: "runs", label: "Runs", icon: RiHistoryLine, badge: p.runs.length || undefined },
      ],
    },
    {
      label: "Evidence",
      entries: [
        { key: "audit", label: "Audit", icon: RiShieldCheckLine },
        { key: "limitations", label: "Limitations", icon: RiErrorWarningLine },
      ],
    },
  ];

  if (p.error) {
    return (
      <Shell groups={groups} selected={null} onSelect={go} header={<TopBar title="Project" />}>
        <div className="flex h-full">
          <EmptyState
            icon={RiFolderLine}
            title={p.error.code === "http_404" ? "Project not found" : "Could not load this project"}
            action={<Button variant="secondary" size="small" leadingIcon={RiArrowLeftSLine} onClick={() => navigate({ name: "projects" })}>All projects</Button>}
          >
            {p.error.message}
          </EmptyState>
        </div>
      </Shell>
    );
  }

  const onWorkspace = tab === "map" || tab === "validation";
  const paramProps = { params, onParamsChange: updateParams, result: p.result, sourceKind: project?.source.kind ?? null, disabled: !project };
  const viewingOld = !!(runId && project?.latest_succeeded_run_id && runId !== project.latest_succeeded_run_id);

  const header = (
    <TopBar
      eyebrow={
        <>
          <button type="button" onClick={() => navigate({ name: "projects" })} className="cursor-pointer hover:text-text-primary">
            Projects
          </button>
          <span>/</span>
          <span className="truncate">{TAB_META[tab]}</span>
        </>
      }
      title={project ? project.name : <Skeleton className="h-6 w-56" />}
      meta={
        project && (
          <>
            <span>{SOURCE_LABEL[project.source.kind]}{project.source.name ? ` · ${project.source.name}` : ""}</span>
            {p.result && <span>· {p.result.summary.aoi_area_ha.toFixed(1)} ha</span>}
            <span>· updated {formatRelative(project.updated_utc)}</span>
          </>
        )
      }
      actions={
        <div className="flex items-center gap-2">
          {running && p.liveStatus && (
            <span className="hidden items-center gap-2 rounded-full border border-separator-border px-3 py-1.5 text-body-2-medium text-text-secondary lg:flex">
              <span className="size-2 animate-pulse rounded-full bg-brand-strong" />
              {p.liveStatus.message} · {p.liveStatus.stage_index}/{p.liveStatus.stage_total}
            </span>
          )}
          <AskAiButton onClick={() => setAiOpen((v) => !v)} active={aiOpen} />
          {p.runs.length > 0 && (
            <RunPicker
              runs={p.runs}
              activeId={p.activeRun?.id ?? null}
              latestId={project?.latest_succeeded_run_id ?? null}
              onPick={(r) => navigate({ name: "project", id: projectId, tab, run: r === project?.latest_succeeded_run_id ? undefined : r })}
            />
          )}
          {onWorkspace && isDesktop && tab === "map" && (
            <>
              <IconButton icon={RiLayoutLeftLine} aria-label={showLeft ? "Hide parameters" : "Show parameters"} onClick={() => setShowLeft((v) => !v)} />
              <IconButton icon={RiLayoutRightLine} aria-label={showRight ? "Hide inspector" : "Show inspector"} onClick={() => setShowRight((v) => !v)} />
            </>
          )}
          <Button variant="primary" size="small" leadingIcon={RiPlayFill} iconOnly={isPhone} aria-label="Run analysis" disabled={running || !project} onClick={() => void run(params)}>
            {running ? "Running…" : "Run analysis"}
          </Button>
        </div>
      }
    />
  );

  return (
    <Shell groups={groups} selected={tab} onSelect={go} wide={onWorkspace || tab === "crowns" || tab === "runs"} header={header}>
      {viewingOld && !onWorkspace && (
        <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-3 border-b border-separator-border bg-status-yellow-background px-4 py-2 text-body-2-medium text-status-yellow-text">
          Viewing an earlier run #{p.activeRun?.number}.
          <button type="button" className="cursor-pointer underline underline-offset-2" onClick={() => navigate({ name: "project", id: projectId, tab })}>
            Back to latest
          </button>
        </div>
      )}

      {/* The map workspace stays mounted so its view, basemap and layers survive tab switches. */}
      <div className={cx("absolute inset-0 flex gap-3 p-3", isPhone ? "flex-col" : "flex-row", !onWorkspace && "pointer-events-none invisible opacity-0")} aria-hidden={!onWorkspace}>
        {tab === "map" && showLeft && !isPhone && (
          <aside className="flex w-[320px] shrink-0 flex-col overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default">
            <ParametersPanel
              {...paramProps}
              activeRun={p.activeRun}
              running={running}
              autoRun={autoRun}
              onAutoRunChange={setAutoRun}
              onRun={() => void run(params)}
            />
          </aside>
        )}

        <div className="relative min-h-[45%] flex-1 overflow-hidden rounded-2xl border border-separator-border bg-background-secondary-default">
          <MapErrorBoundary>
            <MapView
              result={p.result}
              crowns={p.crowns}
              rejected={p.rejected}
              layers={layers}
              imageryOpacity={imageryOpacity}
              mode={mapMode}
              drawPoints={[]}
              validationCorner={vCorner}
              validationBbox={vBbox}
              validationClicks={vClicks}
              onMapClick={onMapClick}
              focus={focus}
              basemap={style.basemap}
              colorBy={style.colorBy}
              palette={style.palette}
              fillOpacity={style.fillOpacity}
              attributionPosition="bottom-right"
            />
          </MapErrorBoundary>
          {p.loadingRun && (
            <div className="pointer-events-none absolute top-3 right-14 z-20 flex items-center gap-2 rounded-full border border-separator-border bg-background-primary-default/90 px-3 py-1.5 text-body-2-medium text-text-secondary shadow-dropdown backdrop-blur-sm">
              <span className="size-2 animate-pulse rounded-full bg-brand-strong" />
              Loading run…
            </div>
          )}
          {p.result && !validating && (
            <div className="pointer-events-none absolute bottom-10 left-3 z-10">
              <MapLegend style={style} crowns={p.crowns} />
            </div>
          )}
          {running && p.liveStatus && (
            <div className="pointer-events-none absolute top-3 left-3 z-20">
              <ProgressOverlay status={p.liveStatus} />
            </div>
          )}
        </div>

        {(validating || showRight || isPhone) && (
          <aside className={cx("flex min-h-0 shrink-0 flex-col overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default", isPhone ? "max-h-[45%]" : "w-[340px]")}>
            {validating ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <ValidationPanel
                  step={vStep}
                  hasCorner={!!vCorner}
                  clicks={vClicks.length}
                  submitting={vSubmitting}
                  result={vResult}
                  onUndo={() => setVClicks((c) => c.slice(0, -1))}
                  onUndoCorner={() => setVCorner(null)}
                  onSubmit={submitValidation}
                  onRestart={resetValidation}
                  onClose={() => go("overview")}
                />
              </div>
            ) : (
              <Tabs selectedKey={inspectorTab} onSelectionChange={(k) => setInspectorTab(k as "results" | "style")} className="flex min-h-0 flex-1 flex-col">
                <TabList aria-label="Inspector" className="px-4">
                  <Tab id="results">Results</Tab>
                  <Tab id="style">Style</Tab>
                </TabList>
                <TabPanel id="results" className="min-h-0 flex-1 overflow-y-auto p-5 outline-none">
                  <ResultsSummary result={p.result} loading={p.loadingRun} />
                </TabPanel>
                <TabPanel id="style" className="min-h-0 flex-1 overflow-y-auto p-5 outline-none">
                  <StylePanel
                    style={style}
                    onStyleChange={setStyle}
                    layers={layers}
                    onLayersChange={setLayers}
                    imageryOpacity={imageryOpacity}
                    onImageryOpacityChange={setImageryOpacity}
                    heightAvailable={!!p.result?.summary.height_available}
                  />
                </TabPanel>
              </Tabs>
            )}
          </aside>
        )}
      </div>

      {!onWorkspace && (
        <div className={cx("absolute inset-0 overflow-y-auto px-4 py-5 md:px-6", viewingOld && "pt-14")}>
          <div className="mx-auto w-full max-w-[1600px]">
            {tab === "overview" && (
              <OverviewPage
                result={p.result}
                crowns={p.crowns}
                run={p.activeRun}
                runs={p.runs}
                loading={!project || p.loadingRun || (!p.result && running)}
                onOpenMap={() => go("map")}
                onValidate={() => go("validation")}
                onOpenLimitations={() => go("limitations")}
                onOpenMapParameters={() => {
                  setShowLeft(true);
                  go("map");
                }}
              />
            )}
            {tab === "crowns" &&
              (p.loadingRun || !p.result ? (
                <TableSkeleton />
              ) : (
                <div className="h-[calc(100dvh-76px-40px)] min-h-[520px]">
                  <CrownsPage
                    crowns={p.crowns}
                    rejected={p.rejected}
                    heightEnabled={p.result.summary.height_available}
                    onShowOnMap={(lngLat, crownId) => {
                      go("map");
                      setFocus({ lngLat, crownId, nonce: Date.now() });
                    }}
                  />
                </div>
              ))}
            {tab === "runs" && (
              <RunsPage
                runs={p.runs}
                activeRunId={p.activeRun?.id ?? null}
                liveStatus={p.liveStatus}
                onView={(r) => navigate({ name: "project", id: projectId, tab: "overview", run: r.id === project?.latest_succeeded_run_id ? undefined : r.id })}
              />
            )}
            {tab === "pipeline" && (p.result ? <PipelinePage key={p.result.job_id} result={p.result} /> : <TableSkeleton />)}
            {tab === "audit" && (p.result ? <AuditPage result={p.result} /> : <TableSkeleton />)}
          </div>
          {running && p.liveStatus && (
            <div className="pointer-events-none fixed right-6 bottom-6 z-20">
              <ProgressOverlay status={p.liveStatus} />
            </div>
          )}
        </div>
      )}
      <AiPanel
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        projectId={projectId}
        projectName={project?.name ?? "Workspace"}
        runId={p.activeRun?.id ?? null}
        running={running}
        onApplyParams={(patch) => {
          const next = { ...params, ...patch };
          setParams(next);
          void run(next);
        }}
      />
    </Shell>
  );
}

function RunPicker({
  runs,
  activeId,
  latestId,
  onPick,
}: {
  runs: { id: string; number: number; status: string; created_utc: string }[];
  activeId: string | null;
  latestId: string | null;
  onPick: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const active = runs.find((r) => r.id === activeId);
  return (
    <Dropdown isOpen={open} onOpenChange={setOpen}>
      <DropdownTrigger className="hidden h-8 items-center gap-1.5 rounded-lg border border-border-button-default bg-background-primary-default px-2.5 text-body-2-medium text-text-primary hover:bg-background-primary-hover sm:flex">
        <RiHistoryLine className="size-4 text-foreground-icon-secondary" aria-hidden />
        {active ? `Run #${active.number}` : "Runs"}
        {active?.id === latestId && <span className="text-text-tertiary">· latest</span>}
        <RiArrowDownSLine className="size-4 text-foreground-icon-secondary" aria-hidden />
      </DropdownTrigger>
      <DropdownPopover aria-label="Runs" placement="bottom end" className="w-[260px]">
        <div className="flex max-h-[320px] flex-col gap-1 overflow-y-auto">
          {[...runs].reverse().map((r) => (
            <DropdownItem
              key={r.id}
              selected={r.id === activeId}
              onMouseEnter={() => {
                if (r.status === "succeeded") prefetchRun(r.id);
              }}
              onSelect={() => {
                if (r.status !== "succeeded") return;
                setOpen(false);
                onPick(r.id);
              }}
              className={cx("justify-between", r.status !== "succeeded" && "cursor-default opacity-60")}
            >
              <span className="flex items-center gap-2">
                <span className="text-body-2-medium">Run #{r.number}</span>
                {r.id === latestId && <Chip variant="caption" color="soft">latest</Chip>}
              </span>
              <span className="text-caption-1-regular text-text-tertiary">
                {r.status === "succeeded" ? formatRelative(r.created_utc) : r.status}
              </span>
            </DropdownItem>
          ))}
        </div>
      </DropdownPopover>
    </Dropdown>
  );
}
