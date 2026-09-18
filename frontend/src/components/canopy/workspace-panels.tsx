import { useMemo } from "react";
import { RiCheckLine, RiPlayFill } from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import { Slider } from "@/components/base/slider/slider";
import { Switch } from "@/components/base/switch/switch";
import { DetectionControls, HeightControls, ImageryControls, LayerControls, type ParamControlProps } from "@/components/canopy/controls";
import type { LayerVisibility } from "@/components/canopy/map-view";
import { DotLabel, Figure, Skeleton, TickMeter } from "@/components/canopy/ui";
import {
  BASEMAPS,
  CANOPY_COLOR,
  COLOR_BY,
  CONFIDENCE_COLORS,
  NO_DATA_COLOR,
  PALETTES,
  rampDomain,
  type BasemapId,
  type ColorBy,
  type PaletteId,
} from "@/lib/mapStyle";
import type { JobParams, JobResult, Run } from "@/types";
import { cx } from "@/utils/cx";

function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h4 className="text-caption-1-medium text-text-tertiary">{children}</h4>
      {action}
    </div>
  );
}

const PARAM_KEYS: (keyof JobParams)[] = [
  "detector",
  "min_crown_diameter_m",
  "veg_index",
  "threshold_mode",
  "threshold_manual",
  "tile_zoom",
  "acquisition_datetime_utc",
  "enable_height",
  "image_m_per_px",
];

export function countChanges(a: JobParams, b: JobParams | undefined): number {
  if (!b) return 0;
  return PARAM_KEYS.filter((k) => (a[k] ?? null) !== (b[k] ?? null)).length;
}

/* ------------------------------------------------------------ parameters */

export function ParametersPanel(
  props: ParamControlProps & {
    activeRun: Run | null;
    running: boolean;
    autoRun: boolean;
    onAutoRunChange: (v: boolean) => void;
    onRun: () => void;
  },
) {
  const changes = countChanges(props.params, props.activeRun?.params);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-separator-border px-5 py-4">
        <div>
          <p className="font-display text-[17px] tracking-[-0.02em] text-text-primary">Parameters</p>
          <p className="text-caption-1-regular text-text-tertiary">
            {props.activeRun ? `Viewing run #${props.activeRun.number}` : "No run yet"}
            {changes > 0 && ` · ${changes} ${changes === 1 ? "change" : "changes"}`}
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        <div className="flex flex-col gap-7">
          <section className="flex flex-col gap-4">
            <SectionTitle>Detection</SectionTitle>
            <DetectionControls {...props} />
          </section>
          <section className="flex flex-col gap-4 border-t border-separator-border pt-6">
            <SectionTitle>Imagery</SectionTitle>
            <ImageryControls {...props} />
          </section>
          <section className="flex flex-col gap-4 border-t border-separator-border pt-6">
            <SectionTitle>Height</SectionTitle>
            <HeightControls {...props} />
          </section>
        </div>
      </div>

      <div className="flex shrink-0 flex-col gap-3 border-t border-separator-border px-5 py-4">
        <Switch size="sm" isSelected={props.autoRun} onChange={props.onAutoRunChange}>
          Re-run on change
        </Switch>
        <Button
          variant="primary"
          size="medium"
          leadingIcon={props.running ? undefined : changes > 0 ? RiPlayFill : RiCheckLine}
          disabled={props.running || props.disabled}
          onClick={props.onRun}
          className="w-full"
        >
          {props.running ? "Running…" : changes > 0 ? `Run with ${changes} ${changes === 1 ? "change" : "changes"}` : "Run again"}
        </Button>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- style */

export interface MapStyleState {
  basemap: BasemapId;
  colorBy: ColorBy;
  palette: PaletteId;
  fillOpacity: number;
}

export function StylePanel({
  style,
  onStyleChange,
  layers,
  onLayersChange,
  imageryOpacity,
  onImageryOpacityChange,
  heightAvailable,
}: {
  style: MapStyleState;
  onStyleChange: (next: MapStyleState) => void;
  layers: LayerVisibility;
  onLayersChange: (next: LayerVisibility) => void;
  imageryOpacity: number;
  onImageryOpacityChange: (v: number) => void;
  heightAvailable: boolean;
}) {
  const set = (patch: Partial<MapStyleState>) => onStyleChange({ ...style, ...patch });
  const continuous = style.colorBy !== "confidence";

  return (
    <div className="flex flex-col gap-7">
      <section className="flex flex-col gap-3">
        <SectionTitle
          action={
            <button
              type="button"
              onClick={() => set({ basemap: "auto" })}
              className={cx("cursor-pointer text-caption-1-medium", style.basemap === "auto" ? "text-text-primary" : "text-text-tertiary hover:text-text-primary")}
            >
              Match theme
            </button>
          }
        >
          Basemap
        </SectionTitle>
        <div className="grid grid-cols-2 gap-2">
          {BASEMAPS.map((b) => {
            const selected = style.basemap === b.id;
            return (
              <button
                key={b.id}
                type="button"
                aria-pressed={selected}
                onClick={() => set({ basemap: b.id })}
                className={cx(
                  "flex cursor-pointer flex-col gap-2 rounded-xl border p-1.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                  selected ? "border-text-primary" : "border-separator-border hover:border-border-button-hover",
                )}
              >
                <span className="h-12 w-full rounded-lg" style={{ background: b.swatch }} />
                <span className="px-1 pb-0.5">
                  <span className="block text-body-2-medium text-text-primary">{b.label}</span>
                  <span className="block truncate text-caption-2-regular text-text-tertiary">{b.description}</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="flex flex-col gap-3 border-t border-separator-border pt-6">
        <SectionTitle>Colour crowns by</SectionTitle>
        <div role="radiogroup" aria-label="Colour crowns by" className="flex flex-col gap-1">
          {COLOR_BY.map((c) => {
            const disabled = c.id === "height_m" && !heightAvailable;
            const selected = style.colorBy === c.id;
            return (
              <button
                key={c.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={disabled}
                onClick={() => set({ colorBy: c.id })}
                className={cx(
                  "flex cursor-pointer items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-border-focus-ring disabled:cursor-not-allowed disabled:opacity-45",
                  selected ? "bg-background-secondary-default" : "hover:bg-background-secondary-hover",
                )}
              >
                <span className="min-w-0">
                  <span className="block text-body-2-medium text-text-primary">{c.label}</span>
                  <span className="block truncate text-caption-1-regular text-text-tertiary">
                    {disabled ? "Needs a run with height enabled" : c.description}
                  </span>
                </span>
                {selected && <RiCheckLine className="size-4 shrink-0 text-text-primary" aria-hidden />}
              </button>
            );
          })}
        </div>

        {continuous && (
          <div className="flex flex-col gap-2 pt-1">
            <p className="text-caption-1-medium text-text-tertiary">Colour scale</p>
            <div className="grid grid-cols-5 gap-1.5">
              {(Object.keys(PALETTES) as PaletteId[]).map((id) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={style.palette === id}
                  title={PALETTES[id].label}
                  onClick={() => set({ palette: id })}
                  className={cx(
                    "h-7 cursor-pointer rounded-md ring-offset-2 ring-offset-background-primary-default outline-none transition-shadow focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                    style.palette === id ? "ring-2 ring-text-primary" : "",
                  )}
                  style={{ background: `linear-gradient(90deg, ${PALETTES[id].stops.join(",")})` }}
                />
              ))}
            </div>
            <p className="text-caption-1-regular text-text-tertiary">{PALETTES[style.palette].label}, stretched between the 5th and 95th percentile.</p>
          </div>
        )}

        <div className="pt-2">
          <Slider
            label="Crown fill"
            minValue={0}
            maxValue={100}
            step={5}
            value={style.fillOpacity}
            onChange={(v) => set({ fillOpacity: v })}
            formatValue={(v) => `${v}%`}
            thumbLabel="Crown fill opacity"
            showTooltip={false}
          />
        </div>
      </section>

      <section className="flex flex-col gap-3 border-t border-separator-border pt-6">
        <SectionTitle>Layers</SectionTitle>
        <LayerControls layers={layers} onLayersChange={onLayersChange} imageryOpacity={imageryOpacity} onImageryOpacityChange={onImageryOpacityChange} />
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- legend */

export function MapLegend({ style, crowns }: { style: MapStyleState; crowns: GeoJSON.FeatureCollection | null }) {
  const meta = COLOR_BY.find((c) => c.id === style.colorBy)!;
  const domain = useMemo(() => rampDomain(crowns, style.colorBy), [crowns, style.colorBy]);
  const fmt = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));

  return (
    <div className="pointer-events-auto w-[220px] rounded-xl border border-separator-border bg-background-primary-default/95 p-3 shadow-dropdown backdrop-blur">
      <p className="text-caption-1-medium text-text-secondary">
        {meta.label}
        {meta.unit && <span className="text-text-tertiary"> · {meta.unit}</span>}
      </p>
      {style.colorBy === "confidence" || !domain ? (
        <div className="mt-2 flex flex-col gap-1">
          <DotLabel color={CONFIDENCE_COLORS.high}>High ≥ 0.70</DotLabel>
          <DotLabel color={CONFIDENCE_COLORS.medium}>Medium 0.45–0.70</DotLabel>
          <DotLabel color={CONFIDENCE_COLORS.low}>Low &lt; 0.45</DotLabel>
        </div>
      ) : (
        <div className="mt-2">
          <div className="h-2.5 w-full rounded-full" style={{ background: `linear-gradient(90deg, ${PALETTES[style.palette].stops.join(",")})` }} />
          <div className="mt-1 flex justify-between text-caption-2-medium text-text-tertiary tabular-nums">
            <span>≤ {fmt(domain[0])}</span>
            <span>≥ {fmt(domain[1])}</span>
          </div>
          {style.colorBy === "height_m" && <DotLabel color={NO_DATA_COLOR}>Not measured</DotLabel>}
        </div>
      )}
    </div>
  );
}

/* --------------------------------------------------------------- results */

export function ResultsSummary({ result, loading }: { result: JobResult | null; loading: boolean }) {
  if (loading || !result) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-10 w-36" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-3 w-20" />
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }
  const s = result.summary;
  const total = s.crown_count || 1;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <DotLabel color={CANOPY_COLOR}>Canopy cover</DotLabel>
        <div className="flex items-end justify-between">
          <Figure value={s.canopy_cover_pct.toFixed(1)} unit="%" size="lg" />
          <span className="pb-1 text-caption-1-regular text-text-tertiary">
            {s.canopy_area_ha.toFixed(1)} of {s.aoi_area_ha.toFixed(1)} ha
          </span>
        </div>
        <TickMeter value={s.canopy_cover_pct / 100} color={CANOPY_COLOR} height="h-4" label="Canopy cover" />
      </div>
      <div className="flex flex-col gap-3 border-t border-separator-border pt-5">
        <DotLabel color="var(--color-brand-strong)">Crowns</DotLabel>
        <div className="flex items-end gap-5">
          <Figure value={s.crown_count} unit="detected" size="md" unitBelow />
          <Figure value={`${s.crown_count_range[0]}–${s.crown_count_range[1]}`} unit="range" size="md" unitBelow />
        </div>
        <div className="flex flex-col gap-2 pt-1">
          {(["high", "medium", "low"] as const).map((b) => (
            <div key={b} className="grid grid-cols-[70px_1fr_34px] items-center gap-2">
              <DotLabel color={CONFIDENCE_COLORS[b]}>{b[0].toUpperCase() + b.slice(1)}</DotLabel>
              <TickMeter value={s.confidence_breakdown[b] / total} color={CONFIDENCE_COLORS[b]} height="h-3" label={b} />
              <span className="text-right text-caption-1-medium tabular-nums">{s.confidence_breakdown[b]}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-1.5 border-t border-separator-border pt-5">
        <DotLabel color="#38bdf8">Height</DotLabel>
        <p className="text-body-2-regular text-text-primary">
          {s.height_available
            ? `${s.height_measured_count} of ${s.crown_count} crowns measured (${s.height_measured_pct.toFixed(0)}%), mean ${s.height_mean_m?.toFixed(0)} m`
            : s.height_unavailable_reason}
        </p>
      </div>
      {result.warnings.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-separator-border pt-5">
          <DotLabel color={CONFIDENCE_COLORS.medium}>{result.warnings.length} warnings</DotLabel>
          <ul className="flex flex-col gap-1.5">
            {result.warnings.map((w) => (
              <li key={w} className="text-caption-1-regular text-text-secondary">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
