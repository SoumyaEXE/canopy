import { useCallback, useEffect, useState } from "react";
import { RiAddLine, RiArrowGoBackLine, RiCheckLine, RiCloseLine, RiErrorWarningLine, RiFolderLine } from "@remixicon/react";
import { api, CanopyApiError } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { Input } from "@/components/base/input/input";
import { Notification, NotificationViewport } from "@/components/base/notification/notification";
import { LimitationsPanel } from "@/components/canopy/limitations-panel";
import { MapView } from "@/components/canopy/map-view";
import { NewProjectModal } from "@/components/canopy/new-project-modal";
import { CreatingOverlay, type CreatingState } from "@/components/canopy/creating-overlay";
import { PlaceSearch } from "@/components/canopy/place-search";
import { Shell, TopBar } from "@/components/canopy/shell";
import type { NavGroup } from "@/components/canopy/sidebar";
import { useProjects } from "@/hooks/useProjects";
import { useRoute, type Route } from "@/lib/router";
import { ProjectView } from "@/pages/project-view";
import { ProjectsPage } from "@/pages/projects";

type LngLat = [number, number];
type GlobalKey = "projects" | "limitations";

const LAYERS_OFF = { imagery: false, canopy: false, crowns: false, rejected: false };

/** Rough planar area of a lon/lat ring in km², only to warn before submitting. The server measures in UTM. */
function approxAreaKm2(points: LngLat[]) {
  if (points.length < 3) return 0;
  const lat0 = (points.reduce((s, p) => s + p[1], 0) / points.length) * (Math.PI / 180);
  const mx = 111_320 * Math.cos(lat0);
  const my = 110_574;
  let sum = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    sum += x1 * mx * (y2 * my) - x2 * mx * (y1 * my);
  }
  return Math.abs(sum) / 2 / 1e6;
}

export default function App() {
  const [route, navigate] = useRoute();
  const list = useProjects();
  const [notices, setNotices] = useState<{ id: number; title: string; message: string }[]>([]);
  const [newOpen, setNewOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [creatingState, setCreatingState] = useState<CreatingState>(null);
  const [drawName, setDrawName] = useState("");

  const notify = useCallback((title: string, message: string) => {
    setNotices((n) => [...n.slice(-2), { id: Date.now() + Math.random(), title, message }]);
  }, []);

  const failed = (title: string) => (err: unknown) =>
    notify(title, err instanceof CanopyApiError ? err.message : "Something unexpected happened. Please try again.");

  // A route change (back button, sidebar) closes the new-project dialog.
  useEffect(() => setNewOpen(false), [route]);

  const openProject = (id: string, tab: "overview" | "map" = "overview") => navigate({ name: "project", id, tab });

  /** Runs a create call behind the growing-folder overlay, held long enough to read, then opens the project. */
  const createWorkspace = async (name: string, source: "file" | "area" | "sample", create: () => Promise<{ project: { id: string } }>) => {
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const started = Date.now();
    setCreating(true);
    setCreatingState({ name, source, phase: "working" });
    try {
      const { project } = await create();
      await sleep(Math.max(0, 1600 - (Date.now() - started)));
      setCreatingState({ name, source, phase: "done" });
      setNewOpen(false);
      await Promise.all([list.refresh(), sleep(650)]);
      openProject(project.id);
    } finally {
      setCreating(false);
      setCreatingState(null);
    }
  };

  const globalGroups = (projects = list.projects): NavGroup<GlobalKey | string>[] => [
    { label: "Workspace", entries: [{ key: "projects", label: "All projects", icon: RiFolderLine, badge: projects?.length || undefined }] },
    ...(projects && projects.length
      ? [
          {
            label: "Recent",
            entries: projects.slice(0, 5).map((p) => ({ key: `p:${p.id}`, label: p.name, icon: RiFolderLine })),
          },
        ]
      : []),
    { label: "Evidence", entries: [{ key: "limitations", label: "Limitations", icon: RiErrorWarningLine }] },
  ];

  const onGlobalSelect = (key: string) => {
    if (key.startsWith("p:")) openProject(key.slice(2));
    else navigate({ name: key as GlobalKey } as Route);
  };

  let page: React.ReactNode;

  if (route.name === "project") {
    page = <ProjectView key={route.id} projectId={route.id} tab={route.tab} runId={route.run} navigate={navigate} notify={notify} />;
  } else if (route.name === "draw") {
    page = (
      <DrawPage
        initialName={drawName}
        onCancel={() => navigate({ name: "projects" })}
        groups={globalGroups()}
        onSelect={onGlobalSelect}
        onCreate={async (name, aoi) => {
          try {
            await createWorkspace(name, "area", () => api.createFromArea(name, aoi));
          } catch (err) {
            failed("Could not create the project")(err);
            throw err;
          }
        }}
      />
    );
  } else if (route.name === "limitations") {
    page = (
      <Shell groups={globalGroups()} selected="limitations" onSelect={onGlobalSelect} header={<TopBar eyebrow="Evidence" title="What this tool cannot do" meta={<span>Plain-language limits of every number CANOPY reports.</span>} />}>
        <div className="absolute inset-0 overflow-y-auto px-4 py-5 md:px-6">
          <div className="mx-auto w-full max-w-[1600px]">
            <LimitationsPanel />
          </div>
        </div>
      </Shell>
    );
  } else {
    page = (
      <Shell
        groups={globalGroups()}
        selected="projects"
        onSelect={onGlobalSelect}
        header={
          <TopBar
            eyebrow="Workspace"
            title="Projects"
            meta={<span>Each project keeps its input, parameters and every run.</span>}
            actions={
              <Button variant="primary" size="small" leadingIcon={RiAddLine} onClick={() => setNewOpen(true)}>
                New project
              </Button>
            }
          />
        }
      >
        <div className="absolute inset-0 overflow-y-auto px-4 py-5 md:px-6">
          <ProjectsPage
            projects={list.error && !list.projects ? [] : list.projects}
            onOpen={(p) => openProject(p.id)}
            onNew={() => setNewOpen(true)}
            onRename={async (p, name) => {
              try {
                await api.renameProject(p.id, name);
                await list.refresh();
              } catch (err) {
                failed("Could not rename the project")(err);
              }
            }}
            onDelete={async (p) => {
              try {
                await api.deleteProject(p.id);
                await list.refresh();
              } catch (err) {
                failed("Could not delete the project")(err);
              }
            }}
          />
        </div>
      </Shell>
    );
  }

  return (
    <>
      {page}

      <NewProjectModal
        isOpen={newOpen}
        onClose={() => setNewOpen(false)}
        submitting={creating}
        onInspect={async (file) => {
          try {
            return (await api.inspectFile(file)).areas;
          } catch (err) {
            failed("Could not inspect the file")(err);
            throw err;
          }
        }}
        onUpload={async (name, file, selection) => {
          try {
            await createWorkspace(name, "file", () => api.createFromFile(name, file, selection));
          } catch (err) {
            failed("Could not create the project")(err);
          }
        }}
        onDraw={(name) => {
          setDrawName(name);
          setNewOpen(false);
          navigate({ name: "draw" });
        }}
        onSample={async (name) => {
          try {
            await createWorkspace(name || "Monfragüe dehesa (sample)", "sample", () => api.createFromSample(name));
          } catch (err) {
            failed("Could not create the project")(err);
          }
        }}
      />

      <CreatingOverlay state={creatingState} />

      {list.error && route.name === "projects" && (
        <NotificationViewport position="top-right">
          <Notification status="error" title="Server unreachable" description={list.error.message} actions={[{ label: "Retry", onClick: () => void list.refresh() }]} />
        </NotificationViewport>
      )}

      <NotificationViewport position="bottom-right">
        {notices.map((n) => (
          <Notification key={n.id} status="error" title={n.title} description={n.message} dismissible onDismiss={() => setNotices((all) => all.filter((x) => x.id !== n.id))} />
        ))}
      </NotificationViewport>
    </>
  );
}

function DrawPage({
  initialName,
  onCancel,
  onCreate,
  groups,
  onSelect,
}: {
  initialName: string;
  onCancel: () => void;
  onCreate: (name: string, aoi: GeoJSON.Polygon) => Promise<void>;
  groups: NavGroup<string>[];
  onSelect: (key: string) => void;
}) {
  const [name, setName] = useState(initialName);
  const [points, setPoints] = useState<LngLat[]>([]);
  const [focus, setFocus] = useState<{ lngLat: LngLat; bounds?: [LngLat, LngLat]; nonce: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const area = approxAreaKm2(points);

  const submit = async () => {
    if (points.length < 3) return;
    setBusy(true);
    try {
      await onCreate(name.trim() || "Drawn area", { type: "Polygon", coordinates: [[...points, points[0]]] });
    } catch {
      setBusy(false);
    }
  };

  return (
    <Shell groups={groups} selected={null} onSelect={onSelect} wide header={<TopBar eyebrow="New project" title="Draw an area of interest" meta={<span>Search a place, then click the corners of the area. Maximum 1 km².</span>} />}>
      <div className="absolute inset-0 p-3">
        <div className="relative size-full overflow-hidden rounded-2xl border border-separator-border">
          <MapView
            result={null}
            crowns={null}
            rejected={null}
            layers={LAYERS_OFF}
            imageryOpacity={0}
            mode="draw"
            drawPoints={points}
            validationCorner={null}
            validationBbox={null}
            validationClicks={[]}
            onMapClick={(p) => setPoints((pts) => [...pts, p])}
            focus={focus}
            basemap="satellite"
            colorBy="confidence"
            palette="viridis"
            fillOpacity={45}
            attributionPosition="bottom-right"
          />

          <div className="absolute top-3 left-3 z-10 w-[min(360px,calc(100%-24px))]">
            <PlaceSearch onSelect={(pl) => setFocus({ lngLat: pl.center, bounds: pl.bounds, nonce: Date.now() })} />
          </div>

          <div className="absolute bottom-10 left-1/2 z-10 flex w-[min(560px,calc(100%-24px))] -translate-x-1/2 flex-col gap-3 rounded-2xl border border-separator-border bg-background-primary-default p-4 shadow-dropdown">
            <div className="flex items-end gap-3">
              <Input label="Project name" placeholder="Drawn area" size="small" value={name} onChange={setName} className="flex-1" />
              <div className="pb-1 text-right">
                <p className="font-display text-[22px] leading-none font-light tabular-nums">
                  {points.length >= 3 ? (area < 0.01 ? (area * 100).toFixed(2) : area.toFixed(2)) : "—"}
                </p>
                <p className="text-caption-1-regular text-text-tertiary">{area < 0.01 ? "ha" : "km²"} · {points.length} points</p>
              </div>
            </div>
            {area > 1 && (
              <p className="text-body-2-regular text-text-error-primary">
                Areas over 1 km² can exceed the processing timeout on the free demo instance. For larger areas, run the tool locally.
              </p>
            )}
            <div className="flex gap-2">
              <Button variant="ghost" size="small" leadingIcon={RiCloseLine} onClick={onCancel}>
                Cancel
              </Button>
              <Button variant="secondary" size="small" leadingIcon={RiArrowGoBackLine} disabled={!points.length} onClick={() => setPoints((p) => p.slice(0, -1))}>
                Undo
              </Button>
              <Button variant="primary" size="small" leadingIcon={RiCheckLine} className="ml-auto" disabled={points.length < 3 || busy} onClick={submit}>
                {busy ? "Creating…" : "Create and analyse"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
