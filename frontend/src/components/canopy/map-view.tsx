import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike, type Map as MlMap } from "maplibre-gl";
import { url } from "@/api/client";
import { useThemeMode } from "@/components/application/theme/theme-toggle";
import { CrownPopup } from "@/components/canopy/crown-popup";
import {
  attributionFor,
  BASEMAPS,
  baseStyle,
  colorExpression,
  rampDomain,
  resolveBasemap,
  type BasemapId,
  type ColorBy,
  type PaletteId,
} from "@/lib/mapStyle";
import type { CrownProps, JobResult } from "@/types";

export interface LayerVisibility {
  imagery: boolean;
  canopy: boolean;
  crowns: boolean;
  rejected: boolean;
}

export type MapMode = "idle" | "draw" | "validate-rect" | "validate-click";

type LngLat = [number, number];

interface MapViewProps {
  result: JobResult | null;
  crowns: GeoJSON.FeatureCollection | null;
  rejected: GeoJSON.FeatureCollection | null;
  layers: LayerVisibility;
  imageryOpacity: number;
  mode: MapMode;
  drawPoints: LngLat[];
  validationCorner: LngLat | null;
  validationBbox: [number, number, number, number] | null;
  validationClicks: LngLat[];
  onMapClick: (lngLat: LngLat) => void;
  focus?: { lngLat: LngLat; crownId?: number; bounds?: [LngLat, LngLat]; nonce: number } | null;
  basemap: BasemapId;
  colorBy: ColorBy;
  palette: PaletteId;
  /** Crown fill opacity, 0 to 100. */
  fillOpacity: number;
  /** Where the attribution sits; on phones the bottom sheet would cover the bottom edge. */
  attributionPosition: "bottom-right" | "top-left";
}

const EMPTY: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

// Result layers, bottom to top, exactly as the spec's layer stack (6.3).
const RESULT_LAYERS = ["imagery", "canopy", "rejected-line", "crowns-fill", "crowns-line", "centroids", "aoi-line"];
const RESULT_SOURCES = ["imagery", "canopy", "rejected", "crowns", "centroids", "aoi"];
// Interaction overlays always sit above the result layers.
const OVERLAY_FIRST = "draw-fill";

function fc(features: GeoJSON.Feature[]): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features };
}

function validLngLat(c: unknown): c is [number, number] {
  return Array.isArray(c) && c.length >= 2 && Number.isFinite(c[0]) && Number.isFinite(c[1]);
}

function parseProps(raw: Record<string, unknown>): CrownProps {
  // MapLibre stringifies nested properties on rendered features; parse them back.
  const p = { ...raw } as Record<string, unknown>;
  for (const key of ["signals", "centroid_lonlat"]) {
    if (typeof p[key] === "string") {
      try { p[key] = JSON.parse(p[key] as string); } catch { /* keep original */ }
    }
  }
  return p as unknown as CrownProps;
}

export function MapView(props: MapViewProps) {
  const { result, crowns, rejected, layers, imageryOpacity, mode } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const popupNode = useMemo(() => document.createElement("div"), []);
  const [ready, setReady] = useState(false);
  const [popupCrown, setPopupCrown] = useState<CrownProps | null>(null);
  const theme = useThemeMode();
  const basemap = resolveBasemap(props.basemap, theme === "dark");
  const colorExpr = useMemo(
    () => colorExpression(props.colorBy, props.palette, rampDomain(crowns, props.colorBy)),
    [props.colorBy, props.palette, crowns],
  );
  const styleRef = useRef({ colorExpr, fillOpacity: props.fillOpacity, basemap });
  styleRef.current = { colorExpr, fillOpacity: props.fillOpacity, basemap };
  const clickRef = useRef(props.onMapClick);
  const modeRef = useRef(mode);
  clickRef.current = props.onMapClick;
  modeRef.current = mode;

  const openPopupRef = useRef((crown: CrownProps) => {
    const map = mapRef.current;
    if (!map || !validLngLat(crown.centroid_lonlat)) return;
    popupRef.current?.remove();
    popupRef.current = new maplibregl.Popup({ closeButton: false, maxWidth: "280px", offset: 8 })
      .setLngLat(crown.centroid_lonlat)
      .setDOMContent(popupNode)
      .addTo(map);
    popupRef.current.on("close", () => setPopupCrown(null));
    setPopupCrown(crown);
  });

  // Fly to a crown (or any point) requested from outside, e.g. a row in the Crowns table.
  const { focus } = props;
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !focus) return;
    if (focus.bounds) {
      map.fitBounds(focus.bounds, { padding: 40, maxZoom: 17, duration: 700 });
      return;
    }
    if (!validLngLat(focus.lngLat)) return;
    map.flyTo({ center: focus.lngLat, zoom: Math.max(map.getZoom(), 18.5), duration: 700 });
    if (focus.crownId == null) return;
    const feature = crowns?.features.find((f) => (f.properties as CrownProps).id === focus.crownId);
    if (!feature) return;
    map.once("moveend", () => openPopupRef.current(feature.properties as CrownProps));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a new nonce is the trigger
  }, [focus?.nonce, ready]);

  // Create the map once.
  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: baseStyle(styleRef.current.basemap),
      center: [-5.95, 39.93],
      zoom: 15,
      maxZoom: 21,
      attributionControl: false,
    });
    mapRef.current = map;
    if (import.meta.env.DEV) (window as unknown as { __canopyMap: MlMap }).__canopyMap = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("load", () => {
      map.addSource("draw", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "draw-fill",
        type: "fill",
        source: "draw",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#ffffff", "fill-opacity": 0.08 },
      });
      map.addLayer({
        id: "draw-line",
        type: "line",
        source: "draw",
        filter: ["!=", ["geometry-type"], "Point"],
        paint: { "line-color": "#ffffff", "line-width": 2 },
      });
      map.addLayer({
        id: "draw-points",
        type: "circle",
        source: "draw",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 5, "circle-color": "#ffffff", "circle-stroke-color": "#0a0a0a", "circle-stroke-width": 1.5 },
      });
      map.addSource("validation", { type: "geojson", data: EMPTY });
      map.addLayer({
        id: "validation-fill",
        type: "fill",
        source: "validation",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "fill-color": "#38bdf8", "fill-opacity": 0.12 },
      });
      map.addLayer({
        id: "validation-rect",
        type: "line",
        source: "validation",
        filter: ["==", ["geometry-type"], "Polygon"],
        paint: { "line-color": "#38bdf8", "line-width": 2 },
      });
      map.addLayer({
        id: "validation-clicks",
        type: "circle",
        source: "validation",
        filter: ["==", ["geometry-type"], "Point"],
        paint: { "circle-radius": 5, "circle-color": "#38bdf8", "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.5 },
      });
      setReady(true);
    });

    map.on("click", (e) => {
      if (modeRef.current !== "idle") {
        clickRef.current([e.lngLat.lng, e.lngLat.lat]);
        return;
      }
      const hits = map.getLayer("crowns-fill")
        ? map.queryRenderedFeatures(e.point, { layers: ["crowns-fill", "centroids"] })
        : [];
      if (!hits.length) return;
      const crown = parseProps(hits[0].properties as Record<string, unknown>);
      openPopupRef.current(crown);
    });

    // The map shares its area with inspectors that open and close, not just window resizes.
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container.current);

    for (const layer of ["crowns-fill", "centroids"]) {
      map.on("mouseenter", layer, () => {
        if (modeRef.current === "idle") map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", layer, () => {
        map.getCanvas().style.cursor = "";
      });
    }

    return () => {
      observer.disconnect();
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, [popupNode]);

  // Basemap switch flips layer visibility; analysis layers above are untouched.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    for (const b of BASEMAPS) map.setLayoutProperty(`basemap-${b.id}`, "visibility", b.id === basemap ? "visible" : "none");
  }, [basemap, ready]);

  // Colour-by and fill opacity restyle in place.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("crowns-fill")) return;
    map.setPaintProperty("crowns-fill", "fill-color", colorExpr);
    map.setPaintProperty("crowns-fill", "fill-opacity", props.fillOpacity / 100);
    map.setPaintProperty("crowns-line", "line-color", colorExpr);
    map.setPaintProperty("centroids", "circle-color", colorExpr);
  }, [colorExpr, props.fillOpacity, ready, result]);

  // Attribution is mandatory and always expanded; it names the imagery actually shown.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const control = new maplibregl.AttributionControl({
      compact: false,
      customAttribution: attributionFor(basemap, result?.provenance.imagery_source),
    });
    map.addControl(control, props.attributionPosition);
    return () => {
      // The map may already be gone (unmount, or StrictMode's double mount).
      if (mapRef.current === map) map.removeControl(control);
    };
  }, [result?.provenance.imagery_source, props.attributionPosition, basemap]);

  // Rebuild result layers whenever a new result (or its GeoJSON) arrives.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    popupRef.current?.remove();
    for (const id of RESULT_LAYERS) if (map.getLayer(id)) map.removeLayer(id);
    for (const id of RESULT_SOURCES) if (map.getSource(id)) map.removeSource(id);
    if (!result) return;

    const corners = result.image_corners as [LngLat, LngLat, LngLat, LngLat];
    const cornersValid = corners.every(validLngLat);
    if (cornersValid) {
      map.addSource("imagery", { type: "image", url: url(result.imagery_png_url), coordinates: corners });
      map.addLayer(
        { id: "imagery", type: "raster", source: "imagery", paint: { "raster-opacity": imageryOpacity / 100, "raster-fade-duration": 0 } },
        OVERLAY_FIRST,
      );
      map.addSource("canopy", { type: "image", url: url(result.canopy_png_url), coordinates: corners });
      map.addLayer(
        { id: "canopy", type: "raster", source: "canopy", paint: { "raster-opacity": 0.25, "raster-fade-duration": 0 } },
        OVERLAY_FIRST,
      );
    }

    map.addSource("rejected", { type: "geojson", data: rejected ?? EMPTY });
    map.addLayer(
      {
        id: "rejected-line",
        type: "line",
        source: "rejected",
        paint: { "line-color": "#a3a3a3", "line-width": 1, "line-dasharray": [2, 2] },
      },
      OVERLAY_FIRST,
    );

    map.addSource("crowns", { type: "geojson", data: crowns ?? EMPTY });
    // Polygons only from zoom 16: MapLibre stutters past a few thousand polygons, and below 16 they are sub-pixel anyway.
    map.addLayer(
      { id: "crowns-fill", type: "fill", source: "crowns", minzoom: 16, paint: { "fill-color": styleRef.current.colorExpr, "fill-opacity": styleRef.current.fillOpacity / 100 } },
      OVERLAY_FIRST,
    );
    map.addLayer(
      { id: "crowns-line", type: "line", source: "crowns", minzoom: 16, paint: { "line-color": styleRef.current.colorExpr, "line-width": 1 } },
      OVERLAY_FIRST,
    );

    const centroids = fc(
      (crowns?.features ?? [])
        .filter((f) => validLngLat((f.properties as CrownProps).centroid_lonlat))
        .map((f) => ({
          type: "Feature",
          properties: f.properties,
          geometry: { type: "Point", coordinates: (f.properties as CrownProps).centroid_lonlat },
        })),
    );
    map.addSource("centroids", { type: "geojson", data: centroids });
    map.addLayer(
      {
        id: "centroids",
        type: "circle",
        source: "centroids",
        paint: {
          "circle-color": styleRef.current.colorExpr,
          "circle-radius": ["interpolate", ["exponential", 1.6], ["zoom"], 12, 2, 16, 4, 20, 8],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 12, 0.5, 17, 1.5],
        },
      },
      OVERLAY_FIRST,
    );

    map.addSource("aoi", { type: "geojson", data: { type: "Feature", properties: {}, geometry: result.aoi } });
    map.addLayer(
      {
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#ffffff", "line-width": 2, "line-dasharray": [3, 2] },
      },
      OVERLAY_FIRST,
    );
    applyVisibility(map, layers, mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- visibility and opacity have their own effects
  }, [result, crowns, rejected, ready]);

  // Fit when the area changes, not on a parameter re-run of the same area (that would throw away the user's zoom).
  const aoiKey = result ? JSON.stringify(result.aoi.coordinates) : "";
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !result) return;
    // Every vertex of a Polygon or MultiPolygon (a KML with several areas is a MultiPolygon).
    const points: number[][] = [];
    const collect = (c: unknown): void => {
      if (!Array.isArray(c)) return;
      if (typeof c[0] === "number") points.push(c as number[]);
      else c.forEach(collect);
    };
    collect((result.aoi as { coordinates?: unknown }).coordinates);
    const lons = points.map((c) => c[0]).filter(Number.isFinite);
    const lats = points.map((c) => c[1]).filter(Number.isFinite);
    if (!lons.length || !lats.length) return;
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ];
    map.fitBounds(bounds, { padding: 48, duration: 600, maxZoom: 18 });
  }, [aoiKey, ready]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyVisibility(map, layers, mode);
  }, [layers, mode, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !map.getLayer("imagery")) return;
    map.setPaintProperty("imagery", "raster-opacity", imageryOpacity / 100);
  }, [imageryOpacity, ready, result]);

  // Drawing and validation overlays.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const pts = props.drawPoints;
    const features: GeoJSON.Feature[] = pts.map((p) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: p } }));
    if (pts.length >= 3) {
      features.push({ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });
    } else if (pts.length === 2) {
      features.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } });
    }
    (map.getSource("draw") as GeoJSONSource).setData(fc(features));
  }, [props.drawPoints, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const features: GeoJSON.Feature[] = props.validationClicks.map((p) => ({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: p },
    }));
    const b = props.validationBbox;
    if (b) {
      features.push({
        type: "Feature",
        properties: {},
        geometry: { type: "Polygon", coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] },
      });
    } else if (props.validationCorner) {
      features.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: props.validationCorner } });
    }
    (map.getSource("validation") as GeoJSONSource).setData(fc(features));
  }, [props.validationClicks, props.validationBbox, props.validationCorner, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const interactive = mode !== "idle";
    map.getCanvasContainer().classList.toggle("canopy-crosshair", interactive);
    if (interactive) {
      map.doubleClickZoom.disable();
      popupRef.current?.remove();
    } else {
      map.doubleClickZoom.enable();
    }
  }, [mode]);

  return (
    <>
      {/* MapLibre sets position: relative on its container, so the absolute box is a wrapper. */}
      <div className="absolute inset-0">
        <div ref={container} className="size-full" />
      </div>
      {popupCrown && createPortal(<CrownPopup crown={popupCrown} heightEnabled={!!result?.summary.height_available} />, popupNode)}
    </>
  );
}

function applyVisibility(map: MlMap, layers: LayerVisibility, mode: MapMode) {
  const hideDetections = mode === "validate-click";
  const set = (id: string, on: boolean) => {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  };
  set("imagery", layers.imagery);
  set("canopy", layers.canopy && !hideDetections);
  set("rejected-line", layers.rejected && !hideDetections);
  set("crowns-fill", layers.crowns && !hideDetections);
  set("crowns-line", layers.crowns && !hideDetections);
  set("centroids", layers.crowns && !hideDetections);
}
