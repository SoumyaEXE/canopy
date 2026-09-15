import { RiDownload2Line, RiFingerprintLine, RiFolderZipLine, RiShieldCheckLine } from "@remixicon/react";
import { IconButton } from "@/components/base/buttons/icon-button";
import { downloadFile, exportsFor } from "@/pages/overview";
import { KeyValue, Panel, PanelHeader } from "@/components/canopy/ui";
import type { JobResult } from "@/types";

export function AuditPage({ result }: { result: JobResult }) {
  const p = result.provenance;
  const s = result.summary;
  return (
    <div className="grid min-h-full grid-cols-1 gap-4 xl:grid-cols-12">
      <div className="flex flex-col gap-4 xl:col-span-7">
        <Panel className="gap-2">
          <PanelHeader title="Exports" icon={RiFolderZipLine} />
          <ul className="flex flex-col">
            {exportsFor(result).map((e) => (
              <li key={e.path} className="flex items-center gap-4 border-b border-separator-border py-3 last:border-b-0">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-background-secondary-default">
                  <e.icon className="size-5 text-foreground-icon-secondary" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-body-medium text-text-primary">
                    {e.label} <span className="text-text-tertiary">· {e.format}</span>
                  </p>
                  <p className="truncate text-body-2-regular text-text-tertiary">{e.description}</p>
                </div>
                <IconButton icon={RiDownload2Line} aria-label={`Download ${e.label} ${e.format}`} onClick={() => downloadFile(e.path)} />
              </li>
            ))}
          </ul>
        </Panel>

        <Panel className="gap-3">
          <PanelHeader title="Reproducibility" icon={RiFingerprintLine} />
          <p className="text-body-2-regular text-text-secondary">
            The same input and parameters produce a byte-identical <span className="font-mono">crowns.geojson</span>: JSON keys are sorted,
            coordinates rounded to 7 decimals (about 1 cm), and zip entries carry a fixed timestamp. Re-run any job and diff the files to check.
          </p>
          <dl>
            <KeyValue k="Job" v={<span className="font-mono">{result.job_id}</span>} />
            <KeyValue k="Created" v={result.created_utc} />
          </dl>
        </Panel>
      </div>

      <Panel className="gap-1 xl:col-span-5">
        <PanelHeader title="Manifest" icon={RiShieldCheckLine} className="mb-1" />
        <dl className="flex flex-col">
          <KeyValue k="Input" v={p.input_type} />
          <KeyValue k="Interpreted as" v={p.interpreted_as ?? "—"} />
          <KeyValue k="Imagery" v={`${p.imagery_source}${p.tile_zoom ? `, zoom ${p.tile_zoom}` : ""}`} />
          <KeyValue k="Fetched" v={p.tile_fetch_utc ?? "—"} />
          <KeyValue k="Resolution" v={`${p.m_per_px} m/px`} />
          <KeyValue k="Resolution source" v={p.resolution_source ?? "—"} />
          <KeyValue k="Working CRS" v={p.working_crs} />
          <KeyValue k="Index p1–p99" v={`${p.index_p1_p99[0]} – ${p.index_p1_p99[1]}`} />
          <KeyValue
            k="Confidence weights"
            v={Object.entries(p.confidence_weights)
              .map(([k, w]) => `${k} ${w.toFixed(2)}`)
              .join(" · ")}
          />
          <KeyValue k="AOI area" v={`${s.aoi_area_ha.toFixed(1)} ha`} />
          <KeyValue k="Rejected regions" v={s.rejected_regions} />
          <KeyValue k="Edge crowns" v={s.edge_crowns} />
          <KeyValue k="Solar source" v={p.solar_source ?? "Height disabled"} />
        </dl>
      </Panel>
    </div>
  );
}
