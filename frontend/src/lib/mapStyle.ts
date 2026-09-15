import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";
import type { CrownProps } from "@/types";

export const CONFIDENCE_COLORS = { high: "#22c55e", medium: "#f59e0b", low: "#ef4444" } as const;
export const CANOPY_COLOR = "#10b981";

// CARTO now requires a key on raster basemaps (free non-commercial tier: carto.com/basemaps/apikey).
// Without one the tiles still load but carry an "API KEY REQUIRED" watermark.
const CARTO_KEY = import.meta.env.VITE_CARTO_API_KEY as string | undefined;

const carto = (style: string) =>
  ["a", "b", "c", "d"].map((s) => {
    const tile = `https://${s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}@2x.png`;
    return CARTO_KEY ? `${tile}?key=${encodeURIComponent(CARTO_KEY)}` : tile;
  });

/* ---------------------------------------------------------------- basemaps */

export type BasemapId = "auto" | "dark" | "light" | "streets" | "satellite";

export const BASEMAPS: { id: Exclude<BasemapId, "auto">; label: string; description: string; swatch: string }[] = [
  { id: "dark", label: "Dark", description: "CARTO Dark Matter", swatch: "linear-gradient(135deg,#0b0b0c,#2a2a2e)" },
  { id: "light", label: "Light", description: "CARTO Positron", swatch: "linear-gradient(135deg,#f4f4f2,#d9dcd6)" },
  { id: "streets", label: "Streets", description: "CARTO Voyager", swatch: "linear-gradient(135deg,#f6efe2,#b9d7e8 60%,#cfe3b4)" },
  { id: "satellite", label: "Satellite", description: "Esri World Imagery", swatch: "linear-gradient(135deg,#27391c,#6b6a3a 55%,#a89a6b)" },
];

export function resolveBasemap(id: BasemapId, dark: boolean): Exclude<BasemapId, "auto"> {
  return id === "auto" ? (dark ? "dark" : "light") : id;
}

export function attributionFor(basemap: Exclude<BasemapId, "auto">, imagerySource: string | null | undefined): string {
  const esri = 'Imagery © <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a> World Imagery';
  const cartoOsm =
    'Basemap © <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>, © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
  const analysed = imagerySource && imagerySource !== "Esri World Imagery" ? `Analysed imagery: ${imagerySource}` : esri;
  const base = basemap === "satellite" ? esri : cartoOsm;
  return base === analysed ? `${base}.` : `${base}. ${analysed}.`;
}

/** Every basemap lives in one style document; switching flips visibility, so analysis layers are never rebuilt. */
export function baseStyle(active: Exclude<BasemapId, "auto">): StyleSpecification {
  const vis = (id: string) => ({ visibility: (id === active ? "visible" : "none") as "visible" | "none" });
  return {
    version: 8,
    sources: {
      "basemap-dark": { type: "raster", tiles: carto("dark_all"), tileSize: 256, maxzoom: 20 },
      "basemap-light": { type: "raster", tiles: carto("light_all"), tileSize: 256, maxzoom: 20 },
      "basemap-streets": { type: "raster", tiles: carto("rastertiles/voyager"), tileSize: 256, maxzoom: 20 },
      "basemap-satellite": {
        type: "raster",
        tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256,
        maxzoom: 19,
      },
    },
    layers: BASEMAPS.map((b) => ({ id: `basemap-${b.id}`, type: "raster" as const, source: `basemap-${b.id}`, layout: vis(b.id) })),
  };
}

/* ---------------------------------------------------------- crown colouring */

export type ColorBy = "confidence" | "area_m2" | "equivalent_diameter_m" | "height_m" | "solidity";
export type PaletteId = "viridis" | "greens" | "magma" | "cividis" | "turbo";

export const COLOR_BY: { id: ColorBy; label: string; unit: string; description: string }[] = [
  { id: "confidence", label: "Confidence", unit: "", description: "High, medium, low buckets (categorical)" },
  { id: "area_m2", label: "Crown area", unit: "m²", description: "Projected crown area" },
  { id: "equivalent_diameter_m", label: "Diameter", unit: "m", description: "Equivalent circular diameter" },
  { id: "height_m", label: "Height", unit: "m", description: "Shadow-derived, measured crowns only" },
  { id: "solidity", label: "Solidity", unit: "", description: "Area ÷ convex hull; low values suggest merges" },
];

/**
 * Perceptually uniform ramps, the defaults in QGIS, ArcGIS Pro and matplotlib for continuous data.
 * Viridis and cividis stay readable for colour-blind viewers; turbo is for spotting outliers.
 */
export const PALETTES: Record<PaletteId, { label: string; stops: string[] }> = {
  viridis: { label: "Viridis", stops: ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"] },
  greens: { label: "Greens", stops: ["#d9f0d3", "#a6dba0", "#5aae61", "#1b7837", "#00441b"] },
  magma: { label: "Magma", stops: ["#1b0c41", "#51127c", "#b73779", "#fc8961", "#fcfdbf"] },
  cividis: { label: "Cividis", stops: ["#00224e", "#434e6c", "#7d7c78", "#bcaf6f", "#fee838"] },
  turbo: { label: "Turbo", stops: ["#30123b", "#28bbec", "#a2fc3c", "#fb8022", "#7a0403"] },
};

export const NO_DATA_COLOR = "#8a8a8a";

/** 5th to 95th percentile, so one huge merged crown does not wash the whole ramp into one colour. */
export function rampDomain(crowns: GeoJSON.FeatureCollection | null, key: ColorBy): [number, number] | null {
  if (!crowns || key === "confidence") return null;
  const values = crowns.features
    .map((f) => (f.properties as CrownProps)[key] as number | null)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v))
    .sort((a, b) => a - b);
  if (!values.length) return null;
  const q = (p: number) => values[Math.min(values.length - 1, Math.max(0, Math.round(p * (values.length - 1))))];
  const lo = q(0.05);
  const hi = q(0.95);
  return lo === hi ? [lo, lo + 1] : [lo, hi];
}

export function colorExpression(key: ColorBy, palette: PaletteId, domain: [number, number] | null): ExpressionSpecification {
  if (key === "confidence" || !domain) {
    return ["match", ["get", "confidence_bucket"], "high", CONFIDENCE_COLORS.high, "medium", CONFIDENCE_COLORS.medium, CONFIDENCE_COLORS.low];
  }
  const stops = PALETTES[palette].stops;
  const [lo, hi] = domain;
  const ramp: (string | number)[] = [];
  stops.forEach((c, i) => ramp.push(lo + ((hi - lo) * i) / (stops.length - 1), c));
  // Unmeasured values (a crown with no height) are null: grey, not the bottom of the ramp.
  return [
    "case",
    ["==", ["get", key], null],
    NO_DATA_COLOR,
    ["interpolate", ["linear"], ["to-number", ["get", key]], ...ramp],
  ] as unknown as ExpressionSpecification;
}
