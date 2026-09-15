import type { ReactNode } from "react";
import { LinkButton } from "@/components/base/buttons/link-button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { Radio, RadioGroup } from "@/components/base/radio/radio";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Slider } from "@/components/base/slider/slider";
import { Switch } from "@/components/base/switch/switch";
import type { LayerVisibility } from "@/components/canopy/map-view";
import type { JobParams, JobResult, SourceKind, VegIndex } from "@/types";

export interface ParamControlProps {
  params: JobParams;
  onParamsChange: (next: JobParams) => void;
  result: JobResult | null;
  sourceKind: SourceKind | null;
  disabled: boolean;
}

export function Hint({ children }: { children: ReactNode }) {
  return <p className="text-body-2-regular text-text-tertiary">{children}</p>;
}

function FieldLabel({ children }: { children: ReactNode }) {
  return <p className="text-body-medium text-text-primary">{children}</p>;
}

/** "2026-09-14T10:30:00Z" <-> "2026-09-14T10:30" for a datetime-local field that is always read as UTC. */
const toLocalField = (iso: string | null) => (iso ? iso.replace(/:\d{2}Z$|Z$/, "").slice(0, 16) : "");
const fromLocalField = (value: string) => (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value) ? `${value}:00Z` : null);

export function DetectionControls({ params, onParamsChange, result, disabled }: ParamControlProps) {
  const set = (patch: Partial<JobParams>) => onParamsChange({ ...params, ...patch });
  const prov = result?.provenance;
  const hasNir = !!prov?.interpreted_as?.includes("NIR");

  // The threshold slider spans the index's own 1st to 99th percentile, so its scale follows the chosen index.
  const sameIndex = prov && prov.veg_index === params.veg_index;
  const [lo, hi] = sameIndex ? prov.index_p1_p99 : [0, 1];
  const otsu = sameIndex ? prov.otsu_value : null;
  const thresholdValue = params.threshold_mode === "manual" && params.threshold_manual != null ? params.threshold_manual : (otsu ?? lo);
  const step = Math.max((hi - lo) / 200, 0.0001);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5">
        <Slider
          label="Min crown diameter"
          minValue={1}
          maxValue={20}
          step={0.5}
          value={params.min_crown_diameter_m}
          onChange={(v) => set({ min_crown_diameter_m: v })}
          formatValue={(v) => `${v.toFixed(1)} m`}
          thumbLabel="Minimum crown diameter in metres"
          isDisabled={disabled}
        />
        <Hint>Smaller regions are rejected; also sets watershed marker spacing.</Hint>
      </div>

      <div className="flex flex-col gap-1.5">
        <Slider
          label="Threshold"
          minValue={lo}
          maxValue={hi}
          step={step}
          value={Math.min(hi, Math.max(lo, thresholdValue))}
          onChange={(v) => set({ threshold_mode: "manual", threshold_manual: Number(v.toFixed(4)) })}
          formatValue={(v) => v.toFixed(3)}
          thumbLabel="Vegetation index threshold"
          isDisabled={disabled || otsu == null}
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-body-2-regular text-text-secondary tabular-nums">Otsu {otsu != null ? otsu.toFixed(3) : "—"}</p>
          {params.threshold_mode === "manual" && (
            <LinkButton size="xs" onClick={() => set({ threshold_mode: "otsu", threshold_manual: null })}>
              Reset to Otsu
            </LinkButton>
          )}
        </div>
        {prov?.threshold_confidence === "low" && (
          <Hint>The index histogram is not clearly two-peaked, so the automatic threshold is a weak guess here.</Hint>
        )}
      </div>

      <div className="flex flex-col gap-2.5">
        <FieldLabel>Vegetation index</FieldLabel>
        <RadioGroup
          aria-label="Vegetation index"
          value={params.veg_index}
          onChange={(v) => set({ veg_index: v as VegIndex, threshold_mode: "otsu", threshold_manual: null })}
          isDisabled={disabled}
          className="flex-row gap-5"
        >
          <Radio value="exg" size="sm">ExG</Radio>
          <Radio value="vari" size="sm">VARI</Radio>
          <Radio value="ndvi" size="sm" isDisabled={!hasNir}>NDVI</Radio>
        </RadioGroup>
        {!hasNir && <Hint>NDVI needs a GeoTIFF with a near-infrared band.</Hint>}
      </div>
    </div>
  );
}

export function ImageryControls({ params, onParamsChange, sourceKind, disabled }: ParamControlProps) {
  const isFile = sourceKind === "geotiff";
  return (
    <div className="flex flex-col gap-2.5">
      <FieldLabel>Tile zoom</FieldLabel>
      <SegmentedControl
        aria-label="Tile zoom"
        selectedKeys={[String(params.tile_zoom)]}
        onSelectionChange={(keys) => {
          const k = [...keys][0];
          if (k) onParamsChange({ ...params, tile_zoom: Number(k) as 18 | 19 });
        }}
        isDisabled={disabled || isFile}
        className="self-start"
      >
        <SegmentedControlItem id="18">Zoom 18</SegmentedControlItem>
        <SegmentedControlItem id="19">Zoom 19</SegmentedControlItem>
      </SegmentedControl>
      {isFile ? (
        <Hint>Uploaded GeoTIFFs keep their own resolution.</Hint>
      ) : params.tile_zoom === 19 ? (
        <Hint>Zoom 19 is often upsampled from zoom 18 in rural areas. Smaller pixels do not guarantee more detail.</Hint>
      ) : (
        <Hint>Esri World Imagery, about 0.3–0.6 m per pixel depending on latitude.</Hint>
      )}
    </div>
  );
}

export function HeightControls({ params, onParamsChange, disabled }: ParamControlProps) {
  const set = (patch: Partial<JobParams>) => onParamsChange({ ...params, ...patch });
  return (
    <div className="flex flex-col gap-4">
      <Switch size="sm" isSelected={params.enable_height} onChange={(v) => set({ enable_height: v })} isDisabled={disabled}>
        Estimate from shadows
      </Switch>
      <Input
        label="Acquisition time (UTC)"
        type="datetime-local"
        size="small"
        value={toLocalField(params.acquisition_datetime_utc)}
        onChange={(v) => set({ acquisition_datetime_utc: fromLocalField(v) })}
        isDisabled={disabled || !params.enable_height}
        hint="Places the sun. Basemap tiles carry no time, so without it height stays off."
      />
    </div>
  );
}

export function LayerControls({
  layers,
  onLayersChange,
  imageryOpacity,
  onImageryOpacityChange,
}: {
  layers: LayerVisibility;
  onLayersChange: (next: LayerVisibility) => void;
  imageryOpacity: number;
  onImageryOpacityChange: (value: number) => void;
}) {
  const row = (key: keyof LayerVisibility, label: string, swatch: ReactNode) => (
    <div className="flex items-center justify-between gap-3">
      <Checkbox size="sm" isSelected={layers[key]} onChange={(v) => onLayersChange({ ...layers, [key]: v })}>
        {label}
      </Checkbox>
      {swatch}
    </div>
  );
  return (
    <div className="flex flex-col gap-3">
      {row("imagery", "Imagery", <span className="size-3 rounded-sm bg-linear-to-br from-amber-700 to-lime-700" />)}
      {row("canopy", "Canopy mask", <span className="size-3 rounded-sm bg-canopy/40" />)}
      {row(
        "crowns",
        "Crowns",
        <span className="flex gap-0.5">
          <span className="size-2 rounded-full bg-confidence-high" />
          <span className="size-2 rounded-full bg-confidence-medium" />
          <span className="size-2 rounded-full bg-confidence-low" />
        </span>,
      )}
      {row("rejected", "Rejected regions", <span className="h-0 w-3 border-t border-dashed border-neutral-400" />)}
      <div className="pt-2">
        <Slider
          label="Imagery opacity"
          minValue={0}
          maxValue={100}
          step={1}
          value={imageryOpacity}
          onChange={onImageryOpacityChange}
          formatValue={(v) => `${v}%`}
          thumbLabel="Imagery opacity"
          showTooltip={false}
        />
      </div>
    </div>
  );
}
