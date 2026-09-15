import { useMemo, useState } from "react";
import {
  RiAddLine,
  RiDeleteBin6Line,
  RiEditLine,
  RiFolderOpenLine,
  RiMore2Fill,
  RiSearchLine,
} from "@remixicon/react";
import { url } from "@/api/client";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { Dropdown, DropdownItem, DropdownPopover, DropdownTrigger } from "@/components/base/dropdown/dropdown";
import { Input } from "@/components/base/input/input";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Modal } from "@/components/canopy/modal";
import { EmptyState, Figure, Panel, Skeleton, SOURCE_LABEL, formatRelative } from "@/components/canopy/ui";
import type { Project } from "@/types";
import { cx } from "@/utils/cx";

type Sort = "recent" | "name" | "cover";

function StatusDot({ project }: { project: Project }) {
  const s = project.latest_run?.status;
  if (s === "queued" || s === "running")
    return (
      <span className="flex items-center gap-1.5 text-caption-1-medium text-text-secondary">
        <span className="size-1.5 animate-pulse rounded-full bg-brand-strong" />
        Running
      </span>
    );
  if (s === "failed")
    return (
      <span className="flex items-center gap-1.5 text-caption-1-medium text-text-error-primary">
        <span className="size-1.5 rounded-full bg-confidence-low" />
        Last run failed
      </span>
    );
  return null;
}

function ProjectCard({
  project,
  index,
  onOpen,
  onRename,
  onDelete,
}: {
  project: Project;
  index: number;
  onOpen: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const s = project.latest_summary;
  const [menuOpen, setMenuOpen] = useState(false);
  const [imgLoaded, setImgLoaded] = useState(false);
  const thumb = project.latest_succeeded_run_id ? url(`/api/jobs/${project.latest_succeeded_run_id}/overlay.png`) : null;

  return (
    <article className="canopy-fade-up group relative flex flex-col overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default transition-[transform,border-color,box-shadow] duration-300 ease-out hover:-translate-y-1 hover:border-border-button-hover hover:shadow-card" style={{ "--canopy-delay": `${index * 55}ms` } as React.CSSProperties}>
      <button type="button" onClick={onOpen} className="absolute inset-0 z-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring focus-visible:ring-inset" aria-label={`Open ${project.name}`} />
      <div className="pointer-events-none relative aspect-[16/9] w-full overflow-hidden bg-background-secondary-default">
        {thumb ? (
          <>
            {!imgLoaded && <Skeleton className="absolute inset-0 rounded-none" />}
            <img
              src={thumb}
              alt=""
              loading="lazy"
              onLoad={() => setImgLoaded(true)}
              className={cx("size-full object-cover transition-[opacity,transform] duration-700 ease-out group-hover:scale-[1.04]", imgLoaded ? "opacity-100" : "opacity-0")}
            />
          </>
        ) : (
          <div className="flex size-full items-center justify-center text-body-2-regular text-text-tertiary">
            {project.latest_run?.status === "failed" ? "No result yet" : "Analysing…"}
          </div>
        )}
        <span className="absolute top-3 left-3 rounded-md bg-black/55 px-1.5 py-0.5 text-caption-1-medium text-white backdrop-blur-sm">
          {SOURCE_LABEL[project.source.kind] ?? project.source.kind}
        </span>
      </div>

      <div className="pointer-events-none relative flex flex-1 flex-col gap-4 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate font-display text-[17px] tracking-[-0.02em] text-text-primary">{project.name}</h3>
            <p className="mt-0.5 truncate text-caption-1-regular text-text-tertiary">
              {project.run_count} {project.run_count === 1 ? "run" : "runs"} · updated {formatRelative(project.updated_utc)}
            </p>
          </div>
          <div className="pointer-events-auto relative z-10">
            <Dropdown isOpen={menuOpen} onOpenChange={setMenuOpen}>
              <DropdownTrigger aria-label="Project actions" className="flex size-8 items-center justify-center rounded-lg text-foreground-icon-secondary hover:bg-background-secondary-hover">
                <RiMore2Fill className="size-4" aria-hidden />
              </DropdownTrigger>
              <DropdownPopover aria-label="Project actions" placement="bottom end" className="w-[200px]">
                <DropdownItem onSelect={() => { setMenuOpen(false); onOpen(); }}>
                  <RiFolderOpenLine className="size-4 text-foreground-icon-secondary" aria-hidden />
                  <span className="text-body-medium">Open</span>
                </DropdownItem>
                <DropdownItem onSelect={() => { setMenuOpen(false); onRename(); }}>
                  <RiEditLine className="size-4 text-foreground-icon-secondary" aria-hidden />
                  <span className="text-body-medium">Rename</span>
                </DropdownItem>
                <DropdownItem onSelect={() => { setMenuOpen(false); onDelete(); }}>
                  <RiDeleteBin6Line className="size-4 text-text-error-primary" aria-hidden />
                  <span className="text-body-medium text-text-error-primary">Delete</span>
                </DropdownItem>
              </DropdownPopover>
            </Dropdown>
          </div>
        </div>

        <div className="mt-auto grid grid-cols-2 gap-3 border-t border-separator-border pt-4">
          <div>
            <p className="text-caption-1-regular text-text-tertiary">Canopy cover</p>
            <Figure value={s ? `${s.canopy_cover_pct.toFixed(1)}%` : "—"} size="sm" className="mt-1" />
          </div>
          <div>
            <p className="text-caption-1-regular text-text-tertiary">Crowns</p>
            <Figure value={s ? `${s.crown_count_range[0]}–${s.crown_count_range[1]}` : "—"} size="sm" className="mt-1" />
          </div>
        </div>
        <StatusDot project={project} />
      </div>
    </article>
  );
}

function CardSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default">
      <Skeleton className="aspect-[16/9] w-full rounded-none" />
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-3 w-1/3" />
        <div className="grid grid-cols-2 gap-3 border-t border-separator-border pt-4">
          <Skeleton className="h-8" />
          <Skeleton className="h-8" />
        </div>
      </div>
    </div>
  );
}

export function ProjectsPage({
  projects,
  onOpen,
  onNew,
  onRename,
  onDelete,
}: {
  projects: Project[] | null;
  onOpen: (p: Project) => void;
  onNew: () => void;
  onRename: (p: Project, name: string) => Promise<void>;
  onDelete: (p: Project) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("recent");
  const [renaming, setRenaming] = useState<Project | null>(null);
  const [newName, setNewName] = useState("");
  const [deleting, setDeleting] = useState<Project | null>(null);
  const [busy, setBusy] = useState(false);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (projects ?? []).filter((p) => !q || p.name.toLowerCase().includes(q) || (p.source.name ?? "").toLowerCase().includes(q));
    return [...list].sort((a, b) =>
      sort === "name"
        ? a.name.localeCompare(b.name)
        : sort === "cover"
          ? (b.latest_summary?.canopy_cover_pct ?? -1) - (a.latest_summary?.canopy_cover_pct ?? -1)
          : b.updated_utc.localeCompare(a.updated_utc),
    );
  }, [projects, query, sort]);

  const totals = useMemo(() => {
    const list = projects ?? [];
    const withResult = list.filter((p) => p.latest_summary);
    return {
      projects: list.length,
      runs: list.reduce((n, p) => n + p.run_count, 0),
      area: withResult.reduce((n, p) => n + (p.latest_summary?.aoi_area_ha ?? 0), 0),
      crowns: withResult.reduce((n, p) => n + (p.latest_summary?.crown_count ?? 0), 0),
    };
  }, [projects]);

  return (
    <div className="mx-auto flex w-full max-w-[1480px] flex-col gap-6">
      {/* Workspace KPIs */}
      <Panel className="grid grid-cols-2 gap-0 p-0 lg:grid-cols-4">
        {[
          { label: "Projects", value: totals.projects, unit: "" },
          { label: "Runs", value: totals.runs, unit: "" },
          { label: "Area analysed", value: totals.area.toFixed(1), unit: "ha" },
          { label: "Crowns detected", value: totals.crowns.toLocaleString(), unit: "latest runs" },
        ].map((k, i) => (
          <div key={k.label} className={cx("canopy-fade-up flex flex-col gap-3 px-5 py-4", i > 0 && "lg:border-l lg:border-separator-border", i % 2 === 1 && "border-l border-separator-border lg:border-l", i >= 2 && "border-t border-separator-border lg:border-t-0")} style={{ "--canopy-delay": `${i * 55}ms` } as React.CSSProperties}>
            <p className="text-body-2-regular text-text-secondary">{k.label}</p>
            {projects ? <div className="canopy-number-in" style={{ "--canopy-delay": `${120 + i * 55}ms` } as React.CSSProperties}><Figure value={k.value} unit={k.unit} size="md" /></div> : <Skeleton className="h-7 w-20" />}
          </div>
        ))}
      </Panel>

      <div className="flex flex-wrap items-center gap-3">
        <div className="canopy-fade-up w-full sm:w-[280px]" style={{ "--canopy-delay": "220ms" } as React.CSSProperties}>
          <Input placeholder="Search projects or files" leadingIcon={RiSearchLine} size="small" value={query} onChange={setQuery} aria-label="Search projects" />
        </div>
        <div className="canopy-fade-up" style={{ "--canopy-delay": "270ms" } as React.CSSProperties}>
          <SegmentedControl aria-label="Sort" selectedKeys={[sort]} onSelectionChange={(k) => { const v = [...k][0]; if (v) setSort(v as Sort); }}>
            <SegmentedControlItem id="recent">Recent</SegmentedControlItem>
            <SegmentedControlItem id="name">Name</SegmentedControlItem>
            <SegmentedControlItem id="cover">Cover</SegmentedControlItem>
          </SegmentedControl>
        </div>
      </div>

      {!projects ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => <CardSkeleton key={i} />)}
        </div>
      ) : shown.length === 0 ? (
        <Panel className="min-h-[320px]">
          <EmptyState
            icon={RiFolderOpenLine}
            title={query ? "No projects match" : "No projects yet"}
            action={!query && <Button variant="primary" size="small" leadingIcon={RiAddLine} onClick={onNew}>New project</Button>}
          >
            {query ? "Try a different name or file." : "Upload a GeoTIFF, GeoJSON, KML or KMZ, or draw an area on the map to start."}
          </EmptyState>
        </Panel>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((p, i) => (
            <ProjectCard
              key={p.id}
              project={p}
              index={i}
              onOpen={() => onOpen(p)}
              onRename={() => { setRenaming(p); setNewName(p.name); }}
              onDelete={() => setDeleting(p)}
            />
          ))}
          <button
            type="button"
            onClick={onNew}
            className="flex min-h-[280px] cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-border-checkbox-default text-text-secondary outline-none transition-colors hover:border-border-button-active hover:text-text-primary focus-visible:ring-2 focus-visible:ring-border-focus-ring"
          >
            <span className="flex size-10 items-center justify-center rounded-full bg-background-secondary-default">
              <RiAddLine className="size-5" aria-hidden />
            </span>
            <span className="text-body-medium">New project</span>
          </button>
        </div>
      )}

      <Modal isOpen={!!renaming} onClose={() => setRenaming(null)} title="Rename project" className="w-[440px]">
        <form
          className="flex flex-col gap-4"
          onSubmit={async (e) => {
            e.preventDefault();
            if (!renaming || !newName.trim()) return;
            setBusy(true);
            await onRename(renaming, newName.trim());
            setBusy(false);
            setRenaming(null);
          }}
        >
          <Input label="Name" value={newName} onChange={setNewName} autoFocus />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="small" onClick={() => setRenaming(null)}>Cancel</Button>
            <Button variant="primary" size="small" type="submit" disabled={busy || !newName.trim()}>{busy ? "Saving…" : "Save"}</Button>
          </div>
        </form>
      </Modal>

      <Modal isOpen={!!deleting} onClose={() => setDeleting(null)} title="Delete project" className="w-[440px]">
        <div className="flex flex-col gap-4">
          <p className="text-body-regular text-text-secondary">
            <span className="text-text-primary">{deleting?.name}</span> and all {deleting?.run_count} of its runs, including their audit bundles, will be
            permanently deleted. This cannot be undone.
          </p>
          {deleting?.latest_run && (deleting.latest_run.status === "running" || deleting.latest_run.status === "queued") && (
            <Chip variant="caption" color="yellow">A run is in progress; wait for it to finish first.</Chip>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="small" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button
              variant="danger"
              size="small"
              disabled={busy}
              onClick={async () => {
                if (!deleting) return;
                setBusy(true);
                await onDelete(deleting);
                setBusy(false);
                setDeleting(null);
              }}
            >
              {busy ? "Deleting…" : "Delete project"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
