import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  RiArrowLeftLine,
  RiCheckLine,
  RiCompass3Line,
  RiFileLine,
  RiImageLine,
  RiMapPin2Line,
  RiPencilRuler2Line,
  RiUploadCloud2Line,
} from "@remixicon/react";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Button } from "@/components/base/buttons/button";
import { FileUpload } from "@/components/base/file-upload/file-upload";
import { Input } from "@/components/base/input/input";
import { ResolutionField } from "@/components/canopy/controls";
import { Modal } from "@/components/canopy/modal";
import type { JobParams, UploadInspection } from "@/types";
import { cx } from "@/utils/cx";

type Source = "upload" | "draw" | "sample";

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const UPLOAD_EXTENSIONS = ["tif", "tiff", "png", "jpg", "jpeg", "webp", "bmp", "geojson", "json", "kml", "kmz"] as const;

const SOURCES: { id: Source; title: string; body: string; icon: typeof RiUploadCloud2Line }[] = [
  { id: "upload", title: "Upload a file", body: "GeoTIFF, PNG or JPG image, or a KML, KMZ or GeoJSON boundary", icon: RiUploadCloud2Line },
  { id: "draw", title: "Draw on the map", body: "Search a place, click the corners of your area", icon: RiPencilRuler2Line },
  { id: "sample", title: "Sample area", body: "Monfragüe holm oak dehesa, Spain", icon: RiCompass3Line },
];

const KIND_LABEL: Record<UploadInspection["kind"], string> = {
  geotiff: "GeoTIFF image",
  image: "Plain image",
  kml: "KML boundary",
  kmz: "KMZ boundary",
  geojson: "GeoJSON boundary",
};

const formatBytes = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const stem = (name: string) => name.replace(/\.[^.]+$/, "");

export function NewProjectModal({
  isOpen,
  onClose,
  onInspect,
  onUpload,
  onDraw,
  onSample,
  submitting,
}: {
  isOpen: boolean;
  onClose: () => void;
  onInspect: (file: File) => Promise<UploadInspection>;
  onUpload: (name: string, file: File, selection?: number[], params?: Partial<JobParams>) => Promise<void>;
  onDraw: (name: string) => void;
  onSample: (name: string) => void;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [source, setSource] = useState<Source>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [info, setInfo] = useState<UploadInspection | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [resolution, setResolution] = useState(0.1);
  const [inspecting, setInspecting] = useState(false);

  const reset = () => {
    setFile(null);
    setInfo(null);
    setSelected(new Set());
  };
  const close = () => {
    reset();
    onClose();
  };

  const inspect = async (next: File) => {
    setInspecting(true);
    try {
      const result = await onInspect(next);
      setFile(next);
      setInfo(result);
      setSelected(new Set(result.areas.length === 1 ? [0] : []));
      if (result.image?.m_per_px) setResolution(result.image.m_per_px);
      if (!name.trim()) setName(stem(next.name));
    } catch {
      reset();
    } finally {
      setInspecting(false);
    }
  };

  const needsResolution = !!info && (info.kind === "image" || (info.kind === "geotiff" && info.image?.georeferenced === false));
  const multiArea = !!info && info.areas.length > 1;
  const canCreate = !!file && !!info && (!multiArea || selected.size > 0) && !submitting;

  const create = () => {
    if (!file || !info) return;
    const selection = multiArea ? [...selected] : undefined;
    const params = needsResolution ? { image_m_per_px: resolution } : undefined;
    void onUpload(name.trim() || stem(file.name), file, selection, params);
  };

  const reviewing = source === "upload" && !!info && !!file;

  return (
    <Modal isOpen={isOpen} onClose={close} title={reviewing ? "Review and create" : "New workspace"} className="w-[640px]">
      <div className="flex flex-col gap-5">
        <Input label="Workspace name" placeholder="e.g. North ridge woodland, 2024 survey" value={name} onChange={setName} />

        <AnimatePresence mode="wait" initial={false}>
          {!reviewing ? (
            <motion.div key="choose" initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.18 }} className="flex flex-col gap-5">
              <div className="flex flex-col gap-2">
                <p className="text-body-medium text-text-primary">Input</p>
                <div role="radiogroup" aria-label="Input" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  {SOURCES.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      role="radio"
                      aria-checked={source === s.id}
                      onClick={() => setSource(s.id)}
                      className={cx(
                        "relative flex cursor-pointer flex-col items-start gap-2 rounded-xl p-3 text-left ring-1 ring-inset outline-none transition-all focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                        source === s.id ? "bg-background-secondary-default ring-text-primary" : "ring-separator-border hover:bg-background-secondary-default/60",
                      )}
                    >
                      {source === s.id && (
                        <span className="absolute top-2.5 right-2.5 flex size-4 items-center justify-center rounded-full bg-text-primary text-background-primary-default">
                          <RiCheckLine className="size-3" aria-hidden />
                        </span>
                      )}
                      <s.icon className={cx("size-5", source === s.id ? "text-text-primary" : "text-foreground-icon-secondary")} aria-hidden />
                      <span className="text-body-medium text-text-primary">{s.title}</span>
                      <span className="text-caption-1-regular text-text-tertiary">{s.body}</span>
                    </button>
                  ))}
                </div>
              </div>

              {source === "upload" && (
                <div className="flex flex-col gap-2">
                  <FileUpload allowedExtensions={UPLOAD_EXTENSIONS} maxBytes={MAX_UPLOAD_BYTES} onUploadComplete={(f) => void inspect(f)} />
                  <p className="text-caption-1-regular text-text-tertiary">
                    {inspecting
                      ? "Checking the file…"
                      : "Nothing is created yet: you review the file first. GeoTIFFs keep their own location and resolution; plain images ask for their resolution; boundary files fetch imagery for the area."}
                  </p>
                </div>
              )}

              {source !== "upload" && (
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" size="small" onClick={close}>
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    size="small"
                    disabled={submitting}
                    onClick={() => (source === "draw" ? onDraw(name.trim()) : onSample(name.trim() || "Monfragüe dehesa"))}
                  >
                    {source === "draw" ? "Continue to map" : "Create workspace"}
                  </Button>
                </div>
              )}
            </motion.div>
          ) : (
            <motion.div key="review" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 12 }} transition={{ duration: 0.18 }} className="flex flex-col gap-4">
              {/* file summary */}
              <div className="flex items-center gap-3 rounded-xl bg-background-secondary-default p-3 ring-1 ring-separator-border ring-inset">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-background-primary-default ring-1 ring-separator-border ring-inset">
                  {info.kind === "image" || info.kind === "geotiff" ? <RiImageLine className="size-5 text-text-secondary" /> : <RiFileLine className="size-5 text-text-secondary" />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-medium text-text-primary">{file.name}</p>
                  <p className="text-caption-1-regular text-text-tertiary">
                    {KIND_LABEL[info.kind]} · {formatBytes(file.size)}
                    {info.image && ` · ${info.image.width.toLocaleString()} × ${info.image.height.toLocaleString()} px`}
                    {info.areas.length > 0 && ` · ${info.areas.length} area${info.areas.length === 1 ? "" : "s"}`}
                  </p>
                </div>
                <Button variant="ghost" size="small" leadingIcon={RiArrowLeftLine} onClick={reset}>
                  Change
                </Button>
              </div>

              {/* what will happen */}
              <ul className="flex flex-col gap-1.5 text-body-2-regular text-text-secondary">
                {info.kind === "image" || (info.kind === "geotiff" && !info.image?.georeferenced) ? (
                  <li className="flex gap-2"><RiMapPin2Line className="mt-0.5 size-4 shrink-0 text-text-tertiary" />No location in this file: it is analysed on its own, and sizes use the resolution below.</li>
                ) : info.kind === "geotiff" ? (
                  <li className="flex gap-2"><RiMapPin2Line className="mt-0.5 size-4 shrink-0 text-text-tertiary" />Located GeoTIFF{info.image?.crs ? ` (${info.image.crs})` : ""}{info.image?.m_per_px ? `, ${info.image.m_per_px} m per pixel` : ""}. Analysed at its own resolution.</li>
                ) : (
                  <li className="flex gap-2"><RiMapPin2Line className="mt-0.5 size-4 shrink-0 text-text-tertiary" />Satellite imagery is fetched for the boundary; large areas use a coarser zoom automatically.</li>
                )}
                <li className="flex gap-2"><RiCheckLine className="mt-0.5 size-4 shrink-0 text-text-tertiary" />The first analysis starts as soon as the workspace is created.</li>
              </ul>

              {needsResolution && (
                <div className="rounded-xl p-3 ring-1 ring-separator-border ring-inset">
                  <ResolutionField value={resolution} onChange={setResolution} />
                </div>
              )}

              {multiArea && (
                <div className="flex flex-col gap-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-body-medium text-text-primary">Choose areas <span className="text-text-tertiary">({selected.size} of {info.areas.length})</span></p>
                    <Checkbox size="sm" isSelected={selected.size === info.areas.length} onChange={(c) => setSelected(c ? new Set(info.areas.map((a) => a.index)) : new Set())}>
                      Select all
                    </Checkbox>
                  </div>
                  <div className="max-h-56 overflow-y-auto rounded-xl p-2 ring-1 ring-separator-border ring-inset">
                    {info.areas.map((area) => (
                      <Checkbox
                        key={area.index}
                        size="sm"
                        isSelected={selected.has(area.index)}
                        onChange={(checked) =>
                          setSelected((current) => {
                            const next = new Set(current);
                            if (checked) next.add(area.index);
                            else next.delete(area.index);
                            return next;
                          })
                        }
                        className="w-full rounded-lg px-2 py-2 hover:bg-background-secondary-default"
                      >
                        {area.name || `Area ${area.index + 1}`}
                      </Checkbox>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between gap-2 border-t border-separator-border pt-4">
                <p className="text-caption-1-regular text-text-tertiary">Creates the workspace “{name.trim() || stem(file.name)}”.</p>
                <div className="flex gap-2">
                  <Button variant="secondary" size="small" onClick={close}>
                    Cancel
                  </Button>
                  <Button variant="primary" size="small" disabled={!canCreate} onClick={create}>
                    {multiArea ? `Create with ${selected.size} area${selected.size === 1 ? "" : "s"}` : "Create workspace"}
                  </Button>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Modal>
  );
}
