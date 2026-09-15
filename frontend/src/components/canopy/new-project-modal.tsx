import { useMemo, useState } from "react";
import { RiCompass3Line, RiPencilRuler2Line, RiUploadCloud2Line } from "@remixicon/react";
import { Checkbox } from "@/components/base/checkbox/checkbox";
import { Button } from "@/components/base/buttons/button";
import { FileUpload } from "@/components/base/file-upload/file-upload";
import { Input } from "@/components/base/input/input";
import { Modal } from "@/components/canopy/modal";
import { cx } from "@/utils/cx";

type Source = "upload" | "draw" | "sample";
type AreaOption = { index: number; name: string | null };

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const UPLOAD_EXTENSIONS = ["tif", "tiff", "geojson", "json", "kml", "kmz"] as const;

const SOURCES: { id: Source; title: string; body: string; icon: typeof RiUploadCloud2Line }[] = [
  { id: "upload", title: "Upload a file", body: "GeoTIFF imagery, or a GeoJSON, KML or KMZ boundary", icon: RiUploadCloud2Line },
  { id: "draw", title: "Draw on the map", body: "Search a place, click the corners of your area", icon: RiPencilRuler2Line },
  { id: "sample", title: "Sample area", body: "Monfragüe holm oak dehesa, Spain", icon: RiCompass3Line },
];

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
  onInspect: (file: File) => Promise<AreaOption[]>;
  onUpload: (name: string, file: File, selection?: number[]) => Promise<void>;
  onDraw: (name: string) => void;
  onSample: (name: string) => void;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [source, setSource] = useState<Source>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [areas, setAreas] = useState<AreaOption[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [inspecting, setInspecting] = useState(false);
  const visibleAreas = useMemo(() => areas ?? [], [areas]);

  const inspect = async (nextFile: File) => {
    setFile(nextFile);
    setInspecting(true);
    try {
      const nextAreas = await onInspect(nextFile);
      if (nextAreas.length <= 1) {
        await onUpload(name.trim() || nextFile.name.replace(/\.[^.]+$/, ""), nextFile);
        return;
      }
      setAreas(nextAreas);
      setSelected(new Set());
    } finally {
      setInspecting(false);
    }
  };

  const submitSelection = async () => {
    if (!file || selected.size === 0) return;
    setInspecting(true);
    try {
      await onUpload(name.trim() || file.name.replace(/\.[^.]+$/, ""), file, [...selected]);
      setAreas(null);
      setFile(null);
    } finally {
      setInspecting(false);
    }
  };

  const toggleAll = (checked: boolean) => setSelected(checked ? new Set(visibleAreas.map((area) => area.index)) : new Set());

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={areas ? "Choose areas" : "New project"} className="w-[620px]">
      <div className="flex flex-col gap-5">
        <Input label="Project name" placeholder="e.g. North ridge woodland, 2024 survey" value={name} onChange={setName} />

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
                  "flex cursor-pointer flex-col items-start gap-2 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                  source === s.id
                    ? "border-text-primary bg-background-secondary-default"
                    : "border-separator-border hover:border-border-button-hover",
                )}
              >
                <s.icon className={cx("size-5", source === s.id ? "text-text-primary" : "text-foreground-icon-secondary")} aria-hidden />
                <span className="text-body-medium text-text-primary">{s.title}</span>
                <span className="text-caption-1-regular text-text-tertiary">{s.body}</span>
              </button>
            ))}
          </div>
        </div>

        {source === "upload" && !areas && (
          <div className="flex flex-col gap-2">
            <FileUpload
              allowedExtensions={UPLOAD_EXTENSIONS}
              maxBytes={MAX_UPLOAD_BYTES}
              onUploadComplete={(nextFile) => void inspect(nextFile)}
            />
            <p className="text-caption-1-regular text-text-tertiary">
              GeoTIFFs must carry a coordinate reference system and are analysed at their own resolution (RGB, RGBA or RGB + NIR). Boundary files
              must hold one polygon up to 1 km²; imagery is fetched for it. The first run starts as soon as the file is checked.
            </p>
          </div>
        )}

        {areas && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-body-medium text-text-primary">{areas.length.toLocaleString()} areas found</p>
                <p className="text-caption-1-regular text-text-tertiary">Select one or more nearby areas to analyse together.</p>
              </div>
              <Checkbox size="sm" isSelected={selected.size === areas.length} onChange={toggleAll}>
                Select all
              </Checkbox>
            </div>
            <div className="max-h-72 overflow-y-auto rounded-xl border border-separator-border p-2">
              {visibleAreas.map((area) => (
                <Checkbox
                  key={area.index}
                  size="sm"
                  isSelected={selected.has(area.index)}
                  onChange={(checked) => setSelected((current) => {
                    const next = new Set(current);
                    if (checked) next.add(area.index);
                    else next.delete(area.index);
                    return next;
                  })}
                  className="w-full rounded-lg px-2 py-2 hover:bg-background-secondary-default"
                >
                  {area.name || `Area ${area.index + 1}`}
                </Checkbox>
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="small" onClick={() => { setAreas(null); setFile(null); }}>
                Back
              </Button>
              <Button variant="primary" size="small" disabled={selected.size === 0 || inspecting} onClick={() => void submitSelection()}>
                {inspecting ? "Creating…" : `Create with ${selected.size.toLocaleString()} area${selected.size === 1 ? "" : "s"}`}
              </Button>
            </div>
          </div>
        )}

        {source !== "upload" && !areas && (
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="small" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="small"
              disabled={submitting}
              onClick={() => (source === "draw" ? onDraw(name.trim()) : onSample(name.trim() || "Monfragüe dehesa"))}
            >
              {source === "draw" ? "Continue to map" : submitting ? "Creating…" : "Create project"}
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
