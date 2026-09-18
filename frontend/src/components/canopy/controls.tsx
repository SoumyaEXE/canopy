import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/api/client";
import { LinkButton } from "@/components/base/buttons/link-button";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Input } from "@/components/base/input/input";
import { Radio, RadioGroup } from "@/components/base/radio/radio";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Slider } from "@/components/base/slider/slider";
import { Switch } from "@/components/base/switch/switch";
import type { LayerVisibility } from "@/components/canopy/map-view";
import { cx } from "@/utils/cx";
import type { ModelsInfo, YoloVariant, JobParams, JobResult, SourceKind, VegIndex } from "@/types";

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

const MODEL_NOTES: Record<YoloVariant, string> = {
  "yolo11n-seg": "Fastest. About 3 M parameters; good for a quick look or a very large area.",
  "yolo11s-seg": "Default. About 10 M parameters; the best balance of accuracy and time on a CPU.",
  "yolo11m-seg": "Most accurate. About 22 M parameters; roughly 3x slower than Balanced.",
};

function ModelPicker({ value, onChange, disabled }: { value: YoloVariant; onChange: (v: YoloVariant) => void; disabled: boolean }) {
  const [info, setInfo] = useState<ModelsInfo | null>(null);
  useEffect(() => {
    let live = true;
    api.models().then((m) => live && setInfo(m)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  const trained = (id: YoloVariant) => !info || info.variants.some((v) => v.id === id && v.trained);
  return (
    <div className="flex flex-col gap-1.5">
      <FieldLabel>AI model</FieldLabel>
      <SegmentedControl
        aria-label="AI model"
        selectedKeys={[value]}
        onSelectionChange={(keys) => {
          const k = [...keys][0];
          if (k) onChange(k as YoloVariant);
        }}
        isDisabled={disabled}
        className="self-start"
      >
        <SegmentedControlItem id="yolo11n-seg" isDisabled={!trained("yolo11n-seg")}>Fast</SegmentedControlItem>
        <SegmentedControlItem id="yolo11s-seg" isDisabled={!trained("yolo11s-seg")}>Balanced</SegmentedControlItem>
        <SegmentedControlItem id="yolo11m-seg" isDisabled={!trained("yolo11m-seg")}>High accuracy</SegmentedControlItem>
      </SegmentedControl>
      <Hint>
        {MODEL_NOTES[value]}
        {info && !trained(value) ? " Not trained on this server yet; the nearest trained size is used." : ""}
        {info && !info.available ? " No trained model is installed, so classical detection is used." : ""}
      </Hint>
    </div>
  );
}

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
        <FieldLabel>Crown detector</FieldLabel>
        <SegmentedControl
          aria-label="Crown detector"
          selectedKeys={[params.detector ?? "hybrid"]}
          onSelectionChange={(keys) => {
            const k = [...keys][0];
            if (k) set({ detector: k as JobParams["detector"] });
          }}
          isDisabled={disabled}
          className="self-start"
        >
          <SegmentedControlItem id="hybrid">Auto</SegmentedControlItem>
          <SegmentedControlItem id="classical">Classical</SegmentedControlItem>
        </SegmentedControl>
        <Hint>
          {params.detector === "classical"
            ? "Blob-detected crown centres, then watershed on the canopy mask. No model."
            : "YOLO11 segmentation fine-tuned on tree crowns, with outlines trimmed to the canopy mask. Falls back to classical if the model is missing or finds nothing."}
        </Hint>
      </div>

      {params.detector !== "classical" && <ModelPicker value={params.yolo_variant ?? "yolo11s-seg"} onChange={(v) => set({ yolo_variant: v })} disabled={disabled} />}

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
        <Hint>Smaller regions are rejected; also sets the smallest crown the blob detector looks for.</Hint>
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

export const RESOLUTION_PRESETS: { label: string; value: number }[] = [
  { label: "Drone", value: 0.03 },
  { label: "Aerial", value: 0.1 },
  { label: "Satellite HD", value: 0.3 },
  { label: "Satellite", value: 0.5 },
  { label: "Coarse", value: 1 },
  { label: "Sentinel-2", value: 10 },
];

/** Ground resolution for a plain image, which carries no scale of its own. */
export function ResolutionField({ value, onChange, disabled }: { value: number | null | undefined; onChange: (v: number) => void; disabled?: boolean }) {
  const [text, setText] = useState(value != null ? String(value) : "0.3");
  const parsed = Number(text);
  const invalid = !(parsed > 0.005 && parsed <= 30);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <Input
          label="Ground resolution"
          size="small"
          value={text}
          onChange={(v) => {
            setText(v);
            const n = Number(v);
            if (n > 0.005 && n <= 30) onChange(n);
          }}
          isDisabled={disabled}
          className="w-32"
        />
        <span className="pb-2 text-body-2-regular text-text-tertiary">metres per pixel</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {RESOLUTION_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            disabled={disabled}
            onClick={() => {
              setText(String(p.value));
              onChange(p.value);
            }}
            className={cx(
              "cursor-pointer rounded-md px-2 py-1 text-caption-1-medium ring-1 ring-inset transition-colors",
              Number(text) === p.value ? "bg-text-primary text-background-primary-default ring-text-primary" : "text-text-secondary ring-separator-border hover:bg-background-secondary-default",
            )}
          >
            {p.label} · {p.value} m
          </button>
        ))}
      </div>
      <Hint>{invalid ? "Enter a value between 0.01 and 30." : "Areas and sizes scale with this, so a wrong value makes every area wrong."}</Hint>
    </div>
  );
}

export function ImageryControls({ params, onParamsChange, sourceKind, disabled }: ParamControlProps) {
  if (sourceKind === "image") {
    return (
      <div className="flex flex-col gap-1.5">
        <FieldLabel>Plain image</FieldLabel>
        <Hint>This image has no location or scale of its own, so tell CANOPY how many metres one pixel covers.</Hint>
        <ResolutionField value={params.image_m_per_px ?? 0.3} onChange={(v) => onParamsChange({ ...params, image_m_per_px: v })} disabled={disabled} />
      </div>
    );
  }
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
