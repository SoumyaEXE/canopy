import { Chip } from "@/components/base/badges/chip";
import type { CrownProps } from "@/types";

const HEIGHT_REASON: Record<string, string> = {
  unavailable: "not measured for this image",
  sun_angle: "sun angle outside the usable range",
  occluded: "shadow falls on another crown",
  no_shadow: "no usable shadow found",
  too_short: "shadow too short to measure",
  implausible_height: "result outside 1 to 80 m, discarded",
};

const BUCKET_CHIP = { high: "lime", medium: "yellow", low: "rose" } as const;
const BUCKET_LABEL = { high: "High", medium: "Medium", low: "Low" } as const;

function Row({ label, value, indent = false }: { label: string; value: React.ReactNode; indent?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className={indent ? "pl-3 text-body-2-regular text-text-secondary" : "text-body-2-medium text-text-secondary"}>{label}</dt>
      <dd className="text-body-2-medium text-text-primary tabular-nums">{value}</dd>
    </div>
  );
}

/** Numbers for people who want them, words for people who do not (spec 6.6). */
export function CrownPopup({ crown, heightEnabled }: { crown: CrownProps; heightEnabled: boolean }) {
  const low = crown.confidence_bucket === "low";
  return (
    <div className="flex w-[248px] flex-col gap-3 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-body-medium text-text-primary">Crown #{crown.id}</p>
        <Chip variant="caption" color={BUCKET_CHIP[crown.confidence_bucket]}>
          {BUCKET_LABEL[crown.confidence_bucket]} ({crown.confidence.toFixed(2)})
        </Chip>
      </div>
      <dl className="flex flex-col gap-1">
        <Row label="Area" value={`${crown.area_m2.toFixed(1)} m²`} />
        <Row label="Diameter" value={`${crown.equivalent_diameter_m.toFixed(1)} m`} />
        <Row
          label="Height"
          value={
            crown.height_m != null ? (
              <>
                {crown.height_m.toFixed(1)} m <span className="text-text-tertiary">(shadow-derived)</span>
              </>
            ) : (
              <span className="text-text-tertiary">{HEIGHT_REASON[crown.height_reason ?? "unavailable"] ?? "not measured"}</span>
            )
          }
        />
      </dl>
      <div className="h-px bg-separator-border" />
      {low && crown.low_confidence_reason ? (
        <p className="text-body-2-regular text-text-primary">{crown.low_confidence_reason}</p>
      ) : (
        <dl className="flex flex-col gap-1">
          <Row label="Confidence" value={`${BUCKET_LABEL[crown.confidence_bucket]} (${crown.confidence.toFixed(2)})`} />
          {crown.signals.detector != null && <Row indent label="AI detector" value={crown.signals.detector.toFixed(2)} />}
          <Row indent label="Shape" value={crown.signals.shape.toFixed(2)} />
          <Row indent label="Size fit" value={crown.signals.size.toFixed(2)} />
          <Row indent label="Separation" value={crown.signals.separation.toFixed(2)} />
          <Row indent label="Shadow" value={heightEnabled ? crown.signals.shadow.toFixed(2) : "not used"} />
        </dl>
      )}
      {crown.touches_edge && (
        <p className="text-caption-1-regular text-text-tertiary">Touches the area boundary, so its area is truncated.</p>
      )}
    </div>
  );
}
