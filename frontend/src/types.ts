// Mirrors backend/app/schemas.py and the result dict built in backend/app/pipeline/__init__.py.

export type VegIndex = "exg" | "vari" | "ndvi";
export type ConfidenceBucket = "high" | "medium" | "low";

export interface JobParams {
  min_crown_diameter_m: number;
  veg_index: VegIndex;
  threshold_mode: "otsu" | "manual";
  threshold_manual: number | null;
  tile_zoom: 18 | 19;
  acquisition_datetime_utc: string | null;
  enable_height: boolean;
}

export type JobStatusValue = "queued" | "running" | "succeeded" | "failed";

export interface StageInfo {
  name: string;
  label: string;
  seconds: number | null;
}

export interface JobStatus {
  job_id: string;
  status: JobStatusValue;
  stage: string | null;
  stage_index: number;
  stage_total: number;
  message: string;
  elapsed_s: number;
  stages: StageInfo[];
  error_code?: string | null;
  error_message?: string | null;
}

export interface Summary {
  aoi_area_m2: number;
  aoi_area_ha: number;
  canopy_area_m2: number;
  canopy_area_ha: number;
  canopy_cover_pct: number;
  crown_count: number;
  crown_count_range: [number, number];
  confidence_breakdown: Record<ConfidenceBucket, number>;
  rejected_regions: number;
  edge_crowns: number;
  mean_crown_area_m2: number | null;
  median_crown_diameter_m: number | null;
  height_available: boolean;
  height_unavailable_reason: string | null;
  height_measured_count: number;
  height_measured_pct: number;
  height_mean_m: number | null;
  height_p90_m: number | null;
  heights_m: number[];
}

export interface Provenance {
  input_type: string;
  interpreted_as: string | null;
  m_per_px: number;
  resolution_source: string | null;
  working_crs: string;
  veg_index: VegIndex;
  index_p1_p99: [number, number];
  threshold_value: number;
  threshold_mode: "otsu" | "manual";
  otsu_value: number;
  threshold_confidence: "high" | "low";
  threshold_bimodality_coefficient: number;
  min_crown_diameter_m: number;
  min_crown_area_m2: number;
  max_crown_area_m2: number;
  min_solidity: number;
  morph_disk_radius_px: number;
  imagery_source: string;
  tile_zoom: number | null;
  tile_fetch_utc: string | null;
  confidence_weights: Record<string, number>;
  sun_elevation_deg: number | null;
  sun_azimuth_deg: number | null;
  solar_source: string | null;
  acquisition_datetime_utc?: string;
}

export interface JobResult {
  job_id: string;
  created_utc: string;
  summary: Summary;
  provenance: Provenance;
  aoi: GeoJSON.Polygon;
  image_corners: [number, number][];
  warnings: string[];
  crowns_geojson_url: string;
  rejected_geojson_url: string;
  crowns_csv_url: string;
  imagery_png_url: string;
  canopy_png_url: string;
  overlay_png_url: string;
  audit_zip_url: string;
}

export interface CrownProps {
  id: number;
  centroid_lonlat: [number, number];
  area_m2: number;
  equivalent_diameter_m: number;
  perimeter_m: number;
  solidity: number;
  touches_edge: boolean;
  height_m: number | null;
  height_reason: string | null;
  confidence: number;
  confidence_bucket: ConfidenceBucket;
  signals: { shape: number; size: number; separation: number; shadow: number };
  low_confidence_reason: string | null;
}

export interface ValidationResult {
  ok: boolean;
  message?: string;
  patch_area_ha?: number;
  clicks?: number;
  detections_in_patch?: number;
  tp?: number;
  fp?: number;
  fn?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  correction_factor?: number | null;
  corrected_count?: number | null;
  summary?: string;
  caveat?: string;
  local_model?: {
    available: boolean;
    reason?: string;
    method?: string;
    training_examples?: number;
    positive_examples?: number;
    negative_examples?: number;
    estimated_count?: number;
    estimated_range?: [number, number];
    note?: string;
  };
}

/** Where the current analysis came from, so parameter changes can re-run it. */
export type AnalysisInput =
  | { kind: "sample" }
  | { kind: "aoi"; aoi: GeoJSON.Polygon }
  | { kind: "file"; file: File; aoi: GeoJSON.Polygon | null };

export interface ApiError {
  error_code: string;
  error_message: string;
}

// ---- projects (backend/app/projects.py) --------------------------------------------------------------

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface RunSummary {
  aoi_area_ha: number;
  canopy_area_ha: number;
  canopy_cover_pct: number;
  crown_count: number;
  crown_count_range: [number, number];
  confidence_breakdown: Record<ConfidenceBucket, number>;
  rejected_regions: number;
  height_available: boolean;
  height_measured_count: number;
  median_crown_diameter_m: number | null;
}

export interface Run {
  id: string;
  project_id: string;
  number: number;
  created_utc: string;
  finished_utc: string | null;
  status: RunStatus;
  params: JobParams;
  summary: RunSummary | null;
  error_code: string | null;
  error_message: string | null;
  stage_message?: string;
}

export type SourceKind = "geotiff" | "kml" | "kmz" | "geojson" | "drawn";

export interface Project {
  id: string;
  name: string;
  created_utc: string;
  updated_utc: string;
  source: { kind: SourceKind; name: string | null; bytes: number | null; sha256: string };
  aoi: GeoJSON.Polygon | null;
  params: JobParams;
  run_count: number;
  latest_run: Run | null;
  latest_succeeded_run_id: string | null;
  latest_summary: RunSummary | null;
  runs?: Run[];
}
