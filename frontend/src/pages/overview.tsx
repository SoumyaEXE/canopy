import { useId, useMemo, useState } from "react";
import {
  RiArrowRightUpLine,
  RiCheckboxMultipleLine,
  RiDownload2Line,
  RiErrorWarningLine,
  RiFileZipLine,
  RiImageLine,
  RiMapPin2Line,
  RiTableLine,
} from "@remixicon/react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { url } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { LinkButton } from "@/components/base/buttons/link-button";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Delta, DotLabel, Figure, Panel, PanelHeader, Skeleton, Sparkline, TickMeter } from "@/components/canopy/ui";
import { CANOPY_COLOR, CONFIDENCE_COLORS } from "@/lib/mapStyle";
import type { CrownProps, JobResult, Run } from "@/types";

export function downloadFile(path: string) {
  const a = document.createElement("a");
  a.href = `${url(path)}?download=1`;
  a.download = path.split("/").pop() ?? "";
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function exportsFor(result: JobResult) {
  return [
    { label: "Crowns", format: "GeoJSON", icon: RiMapPin2Line, path: result.crowns_geojson_url, description: "Crown polygons with every per-crown measurement and signal." },
    { label: "Crowns", format: "CSV", icon: RiTableLine, path: result.crowns_csv_url, description: "The same crowns as a flat table for spreadsheets." },
    { label: "Overlay", format: "PNG", icon: RiImageLine, path: result.overlay_png_url, description: "Imagery with crown outlines coloured by confidence." },
    { label: "Audit bundle", format: "ZIP", icon: RiFileZipLine, path: result.audit_zip_url, description: "All outputs, manifest.json, summary and limitations." },
  ];
}

const BUCKETS = [
  { key: "high", label: "High", color: CONFIDENCE_COLORS.high },
  { key: "medium", label: "Medium", color: CONFIDENCE_COLORS.medium },
  { key: "low", label: "Low", color: CONFIDENCE_COLORS.low },
] as const;

type DistKey = "area_m2" | "equivalent_diameter_m" | "height_m";
const DIST: Record<DistKey, { label: string; unit: string; bin: number }> = {
  area_m2: { label: "Crown area", unit: "m²", bin: 10 },
  equivalent_diameter_m: { label: "Diameter", unit: "m", bin: 1 },
  height_m: { label: "Height", unit: "m", bin: 2 },
};

interface OverviewProps {
  result: JobResult | null;
  crowns: GeoJSON.FeatureCollection | null;
  run: Run | null;
  runs: Run[];
  loading: boolean;
  onOpenMap: () => void;
  onValidate: () => void;
  onOpenLimitations: () => void;
  onOpenMapParameters: () => void;
}

function KpiCard({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <section
      className="relative flex min-h-54.5 min-w-0 flex-col gap-4 overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default p-5 shadow-xs"
      style={{ borderTopColor: color }}
    >
      <span className="absolute inset-x-5 top-0 h-1 rounded-b-full" style={{ background: color }} aria-hidden />
      {children}
    </section>
  );
}

export function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {Array.from({ length: 4 }, (_, i) => (
          <Panel key={i} className="min-h-54.5 gap-4 p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-10 w-32" />
            <Skeleton className="h-3 w-20" />
          </Panel>
        ))}
        <Panel className="min-h-54.5 gap-4 p-5">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-10 w-32" />
          <Skeleton className="h-3 w-20" />
        </Panel>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Panel className="gap-4 xl:col-span-8">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-[260px] w-full" />
        </Panel>
        <Panel className="gap-3 xl:col-span-4">
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-[140px] w-full" />
        </Panel>
      </div>
    </div>
  );
}

/**
 * Reading order follows the spec's argument about certainty (6.5): cover, crown range,
 * confidence, height, then distributions, warnings, actions and limitations.
 */
export function OverviewPage({ result, crowns, run, runs, loading, onOpenMap, onValidate, onOpenLimitations, onOpenMapParameters }: OverviewProps) {
  const chartId = useId().replace(/:/g, "");
  const [dist, setDist] = useState<DistKey>("area_m2");

  // History of finished runs up to the one being viewed, for sparklines and deltas.
  const history = useMemo(() => {
    const done = runs.filter((r) => r.status === "succeeded" && r.summary);
    const idx = run ? done.findIndex((r) => r.id === run.id) : done.length - 1;
    return idx >= 0 ? done.slice(0, idx + 1) : done;
  }, [runs, run]);
  const prev = history.length >= 2 ? history[history.length - 2] : null;

  const distData = useMemo(() => {
    const values = (crowns?.features ?? [])
      .map((f) => (f.properties as CrownProps)[dist] as number | null)
      .filter((v): v is number => typeof v === "number");
    if (!values.length) return [];
    const { bin } = DIST[dist];
    const sorted = [...values].sort((a, b) => a - b);
    const cap = sorted[Math.floor(sorted.length * 0.98)] ?? sorted[sorted.length - 1];
    const n = Math.max(1, Math.ceil(cap / bin));
    const counts = new Array(n + 1).fill(0);
    for (const v of values) counts[Math.min(n, Math.floor(v / bin))]++;
    return counts.map((count, i) => ({ x: i * bin, label: i === n ? `${i * bin}+` : `${i * bin}`, count }));
  }, [crowns, dist]);

  if (loading || !result || !run) return <OverviewSkeleton />;

  const { summary: s, provenance: p } = result;
  const total = s.crown_count || 1;
  const highShare = (s.confidence_breakdown.high / total) * 100;
  const prevS = prev?.summary ?? null;
  const prevHigh = prevS ? (prevS.confidence_breakdown.high / (prevS.crown_count || 1)) * 100 : null;
  const deltaTitle = prev ? `Change against run #${prev.number}` : undefined;
  const thresholdText = `${p.veg_index.toUpperCase()} > ${p.threshold_value.toFixed(3)} (${p.threshold_mode === "otsu" ? "Otsu" : "manual"})`;
  const heightDisabled = !s.height_available || s.heights_m.length === 0;

  return (
    <div className="flex flex-col gap-4">
      {/* 1–4: the headline numbers, in the spec's order of certainty */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <KpiCard color={CANOPY_COLOR}>
          <DotLabel color={CANOPY_COLOR}>Canopy cover</DotLabel>
          <div className="flex items-end justify-between gap-3">
            <Figure value={s.canopy_cover_pct.toFixed(1)} unit="% of area" size="lg" unitBelow />
            <Sparkline data={history.map((r) => r.summary!.canopy_cover_pct)} color={CANOPY_COLOR} />
          </div>
          <div className="flex items-center gap-2">
            <Delta value={prevS ? s.canopy_cover_pct - prevS.canopy_cover_pct : null} suffix=" pts" title={deltaTitle} />
            <span className="truncate text-caption-1-regular text-text-tertiary">
              {s.canopy_area_ha.toFixed(1)} of {s.aoi_area_ha.toFixed(1)} ha
            </span>
          </div>
        </KpiCard>

        <KpiCard color="var(--color-brand-strong)">
          <DotLabel color="var(--color-brand-strong)">Crowns detected</DotLabel>
          <Figure value={s.crown_count} unit="regions detected" size="lg" unitBelow />
          <div className="mt-auto flex items-center gap-2">
            <Delta value={prevS ? s.crown_count - prevS.crown_count : null} title={deltaTitle} />
            <span className="truncate text-caption-1-regular text-text-tertiary">{s.rejected_regions} rejected</span>
          </div>
        </KpiCard>

        <KpiCard color="#f59e0b">
          <DotLabel color="#f59e0b">Plausible range</DotLabel>
          <Figure
            value={`${s.crown_count_range[0]}–${s.crown_count_range[1]}`}
            unit="estimated crowns"
            size={String(s.crown_count_range[1]).length > 3 ? "md" : "lg"}
            unitBelow
          />
          <p className="mt-auto text-caption-1-regular text-text-tertiary">Expected count after accounting for missed or merged regions.</p>
        </KpiCard>

        <KpiCard color={CONFIDENCE_COLORS.high}>
          <DotLabel color={CONFIDENCE_COLORS.high}>High confidence</DotLabel>
          <div className="flex items-end justify-between gap-3">
            <Figure value={highShare.toFixed(0)} unit={`% · ${s.confidence_breakdown.high} crowns`} size="lg" unitBelow />
            <Sparkline data={history.map((r) => (r.summary!.confidence_breakdown.high / (r.summary!.crown_count || 1)) * 100)} color={CONFIDENCE_COLORS.high} />
          </div>
          <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-background-tertiary-default">
            {BUCKETS.map((b) => (
              <span key={b.key} title={`${b.label}: ${s.confidence_breakdown[b.key]} crowns`} style={{ width: `${(s.confidence_breakdown[b.key] / total) * 100}%`, background: b.color }} />
            ))}
          </div>
          <div>
            <Delta value={prevHigh != null ? highShare - prevHigh : null} suffix=" pts" title={deltaTitle} />
          </div>
        </KpiCard>

        <KpiCard color="#38bdf8">
          <DotLabel color="#38bdf8">Height</DotLabel>
          {s.height_available && s.height_mean_m != null ? (
            <>
              <Figure value={s.height_mean_m.toFixed(0)} unit={`m mean · p90 ${s.height_p90_m?.toFixed(0)} m`} size="lg" unitBelow />
              <span className="text-caption-1-regular text-text-tertiary">
                Measured for {s.height_measured_count} of {s.crown_count} ({s.height_measured_pct.toFixed(0)}%)
              </span>
            </>
          ) : (
            <>
              <Figure value="—" unit="not estimated" size="lg" unitBelow />
              <p className="line-clamp-2 text-caption-1-regular text-text-tertiary">
                {s.height_unavailable_reason}{" "}
                <button type="button" onClick={onOpenMapParameters} className="cursor-pointer text-text-primary underline-offset-2 hover:underline">
                  Set acquisition time
                </button>
              </p>
            </>
          )}
        </KpiCard>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        {/* Distribution */}
        <Panel className="gap-4 xl:col-span-8">
          <PanelHeader
            eyebrow={`Per crown · run #${run.number}`}
            title={`${DIST[dist].label} distribution`}
            action={
              <SegmentedControl aria-label="Distribution" selectedKeys={[dist]} onSelectionChange={(k) => { const v = [...k][0]; if (v) setDist(v as DistKey); }}>
                <SegmentedControlItem id="area_m2">Area</SegmentedControlItem>
                <SegmentedControlItem id="equivalent_diameter_m">Diameter</SegmentedControlItem>
                <SegmentedControlItem id="height_m" isDisabled={heightDisabled}>Height</SegmentedControlItem>
              </SegmentedControl>
            }
          />
          <div className="h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={distData} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                <defs>
                  <pattern id={`halftone-${chartId}`} width="4" height="4" patternUnits="userSpaceOnUse">
                    <circle cx="2" cy="2" r="1.05" fill={CANOPY_COLOR} />
                  </pattern>
                  <linearGradient id={`fade-${chartId}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-background-primary-default)" stopOpacity={0} />
                    <stop offset="100%" stopColor="var(--color-background-primary-default)" stopOpacity={0.9} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="var(--color-separator-border)" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }} interval="preserveStartEnd" minTickGap={24} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--color-text-tertiary)", fontSize: 11 }} width={40} />
                <Tooltip
                  cursor={{ stroke: "var(--color-border-button-hover)" }}
                  contentStyle={{ background: "var(--color-background-primary-default)", border: "1px solid var(--color-border-button-default)", borderRadius: 10, fontSize: 12 }}
                  labelFormatter={(l) => `${l} ${DIST[dist].unit}`}
                  formatter={(v) => [`${v} crowns`, ""]}
                  separator=""
                />
                <Area type="monotone" dataKey="count" stroke="none" fill={`url(#halftone-${chartId})`} isAnimationActive={false} />
                <Area type="monotone" dataKey="count" stroke={CANOPY_COLOR} strokeWidth={1.75} fill={`url(#fade-${chartId})`} activeDot={{ r: 3 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            {dist === "height_m"
              ? `Shadow-derived heights for ${s.height_measured_count} crowns that passed the quality gate; biased low by about one crown radius.`
              : `Median diameter ${s.median_crown_diameter_m?.toFixed(1) ?? "—"} m · mean area ${s.mean_crown_area_m2?.toFixed(0) ?? "—"} m² · ${thresholdText} · ${p.m_per_px.toFixed(2)} m/px.`}
          </p>
        </Panel>

        {/* Confidence + map */}
        <div className="flex flex-col gap-4 xl:col-span-4">
          <Panel className="gap-4">
            <PanelHeader eyebrow="Per-crown score" title="Confidence breakdown" />
            <ul className="flex flex-col gap-3">
              {BUCKETS.map((b) => {
                const n = s.confidence_breakdown[b.key];
                return (
                  <li key={b.key} className="grid grid-cols-[76px_1fr_52px] items-center gap-3">
                    <DotLabel color={b.color}>{b.label}</DotLabel>
                    <TickMeter value={n / total} color={b.color} height="h-3.5" label={`${b.label} confidence`} />
                    <span className="text-right text-body-2-medium text-text-primary tabular-nums">{n}</span>
                  </li>
                );
              })}
            </ul>
          </Panel>

          <button
            type="button"
            onClick={onOpenMap}
            className="group relative min-h-[180px] flex-1 cursor-pointer overflow-hidden rounded-2xl border border-separator-border bg-background-secondary-default text-left outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring"
          >
            <img src={url(result.overlay_png_url)} alt="Imagery with crown outlines coloured by confidence" className="absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-[1.03]" />
            <div className="absolute inset-0 bg-linear-to-t from-black/60 via-transparent to-transparent" />
            <div className="absolute inset-x-4 bottom-4 flex items-end justify-between gap-2 text-white">
              <div>
                <p className="text-caption-1-regular text-white/70">{p.imagery_source}{p.tile_zoom ? ` · zoom ${p.tile_zoom}` : ""}</p>
                <p className="font-display text-[17px]">Open in map</p>
              </div>
              <RiArrowRightUpLine className="size-5" aria-hidden />
            </div>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-12">
        {/* 5. Warnings, always expanded */}
        <Panel className="gap-4 md:col-span-2 xl:col-span-6">
          <PanelHeader eyebrow="Read before using the numbers" title={`${result.warnings.length} ${result.warnings.length === 1 ? "warning" : "warnings"}`} icon={RiErrorWarningLine} />
          {result.warnings.length ? (
            <ul className="flex flex-col">
              {result.warnings.map((w) => (
                <li key={w} className="flex items-start gap-3 border-t border-separator-border py-3 first:border-t-0 first:pt-0">
                  <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-confidence-medium" />
                  <span className="text-body-2-regular text-text-primary">{w}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-body-2-regular text-text-tertiary">No warnings for this run.</p>
          )}
        </Panel>

        {/* 6. Actions */}
        <Panel className="gap-4 xl:col-span-3">
          <PanelHeader eyebrow="Run outputs" title="Exports" icon={RiDownload2Line} />
          <ul className="-mx-2 flex flex-col">
            {exportsFor(result).map((e) => (
              <li key={e.path}>
                <button
                  type="button"
                  onClick={() => downloadFile(e.path)}
                  className="group flex w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-left outline-none transition-colors hover:bg-background-secondary-hover focus-visible:ring-2 focus-visible:ring-border-focus-ring"
                >
                  <e.icon className="size-4 shrink-0 text-foreground-icon-secondary" aria-hidden />
                  <span className="flex-1 text-body-2-medium text-text-primary">{e.label}</span>
                  <span className="text-caption-1-medium text-text-tertiary">{e.format}</span>
                </button>
              </li>
            ))}
          </ul>
          <Button variant="secondary" size="small" leadingIcon={RiCheckboxMultipleLine} onClick={onValidate} className="mt-auto w-full shrink-0">
            Validate detections
          </Button>
        </Panel>

        {/* 7. Limitations, a permanent link */}
        <Panel className="gap-3 border-transparent bg-neutral-950 text-white xl:col-span-3 dark:bg-brand">
          <p className="text-caption-1-regular text-white/60 dark:text-brand-foreground/70">What this tool cannot do</p>
          <p className="font-display text-[21px] leading-[1.15] font-normal tracking-[-0.02em] text-white dark:text-brand-foreground">
            No carbon, biomass or credit figures. Not even roughly.
          </p>
          <p className="text-body-2-regular text-white/60 dark:text-brand-foreground/70">Merged crowns, hidden understory, lawns that look like trees, unknown imagery dates.</p>
          <LinkButton variant="secondary" size="small" trailingIcon={RiArrowRightUpLine} onClick={onOpenLimitations} className="mt-auto self-start text-brand dark:text-brand-foreground">
            Read the limitations
          </LinkButton>
        </Panel>
      </div>
    </div>
  );
}
