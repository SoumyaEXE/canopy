import { RiCheckLine, RiCloseCircleLine, RiDownload2Line, RiEyeLine, RiHistoryLine, RiLoader4Line } from "@remixicon/react";
import { url } from "@/api/client";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { Table, TableBody, TableCell, TableColumn, TableHeader, TableRow } from "@/components/base/table/table";
import { EmptyState, Panel, PanelHeader, formatRelative } from "@/components/canopy/ui";
import type { JobParams, JobStatus, Run } from "@/types";

const PARAM_LABEL: Record<keyof JobParams, string> = {
  detector: "Detector",
  yolo_variant: "Model",
  min_crown_diameter_m: "Min crown",
  veg_index: "Index",
  threshold_mode: "Threshold",
  threshold_manual: "Manual value",
  tile_zoom: "Zoom",
  acquisition_datetime_utc: "Acquisition",
  enable_height: "Height",
  image_m_per_px: "Image resolution",
};

function formatParam(key: keyof JobParams, p: JobParams): string {
  const v = p[key];
  if (key === "min_crown_diameter_m") return `${Number(v).toFixed(1)} m`;
  if (key === "veg_index") return String(v).toUpperCase();
  if (key === "detector") return v === "classical" ? "classical" : "auto";
  if (key === "yolo_variant") return p.detector === "classical" ? "—" : ({ "yolo11n-seg": "fast (n)", "yolo11s-seg": "balanced (s)", "yolo11m-seg": "high accuracy (m)" }[String(v)] ?? "balanced (s)");
  if (key === "threshold_mode") return p.threshold_mode === "manual" ? `manual ${p.threshold_manual}` : "Otsu";
  if (key === "enable_height") return v ? "on" : "off";
  if (key === "image_m_per_px") return v == null ? "—" : `${v} m/px`;
  if (key === "acquisition_datetime_utc") return v ? String(v).replace("T", " ").replace(":00Z", " UTC") : "unknown";
  return v == null ? "—" : String(v);
}

/** What changed from the previous run, so a history row explains itself. */
function paramChanges(run: Run, prev: Run | undefined): string[] {
  const keys: (keyof JobParams)[] = ["detector", "yolo_variant", "min_crown_diameter_m", "veg_index", "threshold_mode", "tile_zoom", "enable_height", "acquisition_datetime_utc"];
  if (!prev) return keys.map((k) => `${PARAM_LABEL[k]} ${formatParam(k, run.params)}`).slice(0, 3);
  return keys.filter((k) => formatParam(k, run.params) !== formatParam(k, prev.params)).map((k) => `${PARAM_LABEL[k]} ${formatParam(k, prev.params)} → ${formatParam(k, run.params)}`);
}

function StatusChip({ run, live }: { run: Run; live: JobStatus | null }) {
  if (run.status === "succeeded")
    return (
      <Chip variant="caption" color="lime">
        <RiCheckLine className="mr-0.5 size-3.5" aria-hidden /> Done
      </Chip>
    );
  if (run.status === "failed")
    return (
      <Chip variant="caption" color="rose" title={run.error_message ?? undefined}>
        <RiCloseCircleLine className="mr-0.5 size-3.5" aria-hidden /> Failed
      </Chip>
    );
  return (
    <Chip variant="caption" color="blue">
      <RiLoader4Line className="mr-0.5 size-3.5 animate-spin" aria-hidden />
      {live?.status === "running" ? `${live.stage_index}/${live.stage_total}` : "Queued"}
    </Chip>
  );
}

export function RunsPage({
  runs,
  activeRunId,
  liveStatus,
  onView,
}: {
  runs: Run[];
  activeRunId: string | null;
  liveStatus: JobStatus | null;
  onView: (run: Run) => void;
}) {
  const ordered = [...runs].reverse();
  const byNumber = new Map(runs.map((r) => [r.number, r]));

  return (
    <Panel className="gap-4 p-0">
      <div className="px-5 pt-5">
        <PanelHeader eyebrow="Every run keeps its parameters and outputs" title="Run history" icon={RiHistoryLine} />
      </div>
      {runs.length === 0 ? (
        <EmptyState icon={RiHistoryLine} title="No runs yet" className="py-12">
          Runs appear here as soon as they start.
        </EmptyState>
      ) : (
        <Table aria-label="Runs" size="sm">
          <TableHeader>
            <TableColumn isRowHeader>Run</TableColumn>
            <TableColumn>Status</TableColumn>
            <TableColumn>Started</TableColumn>
            <TableColumn>Changes</TableColumn>
            <TableColumn>Cover</TableColumn>
            <TableColumn>Crowns</TableColumn>
            <TableColumn>High conf.</TableColumn>
            <TableColumn> </TableColumn>
          </TableHeader>
          <TableBody items={ordered}>
            {(r) => {
              const s = r.summary;
              const changes = paramChanges(r, byNumber.get(r.number - 1));
              const viewing = r.id === activeRunId;
              return (
                <TableRow id={r.id} className={viewing ? "bg-background-secondary-default" : undefined}>
                  <TableCell>
                    <span className="flex items-center gap-2">
                      <span className="font-display text-[15px] tabular-nums">#{r.number}</span>
                      {viewing && <Chip variant="caption" color="soft">Viewing</Chip>}
                    </span>
                  </TableCell>
                  <TableCell>
                    <StatusChip run={r} live={r.status === "running" || r.status === "queued" ? liveStatus : null} />
                  </TableCell>
                  <TableCell className="text-text-secondary" >{formatRelative(r.created_utc)}</TableCell>
                  <TableCell className="max-w-[340px]">
                    {r.status === "failed" ? (
                      <span className="line-clamp-2 text-text-error-primary">{r.error_message}</span>
                    ) : changes.length ? (
                      <span className="line-clamp-2 text-text-secondary">{changes.join(" · ")}</span>
                    ) : (
                      <span className="text-text-tertiary">Same parameters</span>
                    )}
                  </TableCell>
                  <TableCell className="tabular-nums">{s ? `${s.canopy_cover_pct.toFixed(1)}%` : "—"}</TableCell>
                  <TableCell className="tabular-nums">{s ? `${s.crown_count_range[0]}–${s.crown_count_range[1]}` : "—"}</TableCell>
                  <TableCell className="tabular-nums">{s ? `${Math.round((s.confidence_breakdown.high / (s.crown_count || 1)) * 100)}%` : "—"}</TableCell>
                  <TableCell>
                    {r.status === "succeeded" && (
                      <span className="flex justify-end gap-1">
                        <Button variant="secondary" size="xs" leadingIcon={RiEyeLine} onClick={() => onView(r)} disabled={viewing}>
                          View
                        </Button>
                        <Button
                          variant="secondary"
                          size="xs"
                          iconOnly
                          leadingIcon={RiDownload2Line}
                          aria-label={`Download audit bundle for run ${r.number}`}
                          onClick={() => window.open(url(`/api/jobs/${r.id}/audit.zip`), "_blank", "noopener")}
                        />
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              );
            }}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}
