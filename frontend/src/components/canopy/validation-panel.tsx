import { RiArrowGoBackLine, RiBarChart2Line, RiCheckLine, RiCloseLine, RiFocus3Line, RiPlantLine } from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import type { ValidationResult } from "@/types";

export const MIN_CLICKS = 15;

interface ValidationPanelProps {
  step: "rect" | "click" | "done";
  hasCorner: boolean;
  clicks: number;
  submitting: boolean;
  result: ValidationResult | null;
  onUndo: () => void;
  onUndoCorner: () => void;
  onSubmit: () => void;
  onRestart: () => void;
  onClose: () => void;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-h-19.5 flex-col justify-between rounded-2xl border border-separator-border bg-background-secondary-default p-3">
      <p className="text-body-2-medium text-text-secondary">{label}</p>
      <p className="font-display text-[25px] leading-none font-light text-text-primary tabular-nums">{value}</p>
    </div>
  );
}

function RateBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2 text-body-2-medium text-text-secondary">
        <span>{label}</span>
        <span className="tabular-nums text-text-primary">{value.toFixed(0)}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-background-tertiary-default">
        <div className="h-full rounded-full transition-[width]" style={{ width: `${value}%`, background: color }} />
      </div>
    </div>
  );
}

export function ValidationPanel(props: ValidationPanelProps) {
  const { step, result } = props;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-body-medium text-text-secondary">Ground-truth check</h2>
        <Button variant="ghost" size="xs" leadingIcon={RiCloseLine} onClick={props.onClose}>
          Exit
        </Button>
      </div>

      <ol className="flex flex-col gap-1 text-body-2-regular text-text-secondary">
        <li className={step === "rect" ? "text-text-primary" : undefined}>1. Mark a small patch on the map.</li>
        <li className={step === "click" ? "text-text-primary" : undefined}>2. Click the centre of every tree you can see in it.</li>
        <li className={step === "done" ? "text-text-primary" : undefined}>3. Compare against the detections.</li>
      </ol>

      {step === "rect" && (
        <p className="rounded-2xl bg-background-secondary-default p-4 text-body-regular text-text-primary">
          {props.hasCorner
            ? "One corner is marked. Click the opposite corner to create the patch."
            : "Click one corner of a small patch you can inspect closely, around a quarter of a hectare."}
        </p>
      )}

      {step === "click" && (
        <>
          <div className="rounded-2xl bg-background-secondary-default p-4">
            <p className="text-body-2-medium text-text-primary">Patch ready</p>
            <p className="text-body-regular text-text-primary">
              The blue box is your sample area. Detections are hidden so they do not steer you. Click the centre of every visible tree inside the box.
            </p>
            <p className="mt-2 text-title-2-medium text-text-primary tabular-nums">
              {props.clicks} <span className="text-body-regular text-text-secondary">trees marked, {MIN_CLICKS} minimum</span>
            </p>
          </div>
          {result && !result.ok && <p className="text-body-2-regular text-text-error-primary">{result.message}</p>}
          <div className="flex gap-2">
            <Button variant="secondary" size="small" leadingIcon={RiArrowGoBackLine} onClick={props.onUndo} disabled={props.clicks === 0}>
              Undo
            </Button>
            <Button variant="ghost" size="small" onClick={props.onRestart}>
              New patch
            </Button>
            <Button
              variant="primary"
              size="small"
              className="flex-1"
              disabled={props.clicks < MIN_CLICKS || props.submitting}
              onClick={props.onSubmit}
            >
              {props.submitting ? "Computing…" : "Compute metrics"}
            </Button>
          </div>
        </>
      )}

      {step === "rect" && props.hasCorner && (
        <Button variant="secondary" size="small" leadingIcon={RiArrowGoBackLine} onClick={props.onUndoCorner}>
          Undo corner
        </Button>
      )}

      {step === "done" && result?.ok && (
        <>
          <div className="flex items-center gap-2 rounded-2xl bg-background-secondary-default p-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-status-lime-background text-status-lime-text">
              <RiCheckLine className="size-5" aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-body-medium text-text-primary">Validation complete</p>
              <p className="text-body-2-regular text-text-tertiary">Your marked patch has been compared with the detections.</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Metric label="Precision" value={result.precision!.toFixed(2)} />
            <Metric label="Recall" value={result.recall!.toFixed(2)} />
            <Metric label="F1" value={result.f1!.toFixed(2)} />
            <Metric label="Correction factor" value={result.correction_factor != null ? result.correction_factor.toFixed(2) : "n/a"} />
          </div>
          <div className="rounded-2xl border border-separator-border bg-background-primary-default p-4">
            <div className="mb-4 flex items-center gap-2">
              <RiBarChart2Line className="size-4 text-foreground-icon-secondary" aria-hidden />
              <p className="text-body-medium text-text-primary">Detection quality</p>
            </div>
            <div className="flex flex-col gap-3">
              <RateBar label="Precision" value={(result.precision ?? 0) * 100} color="#38bdf8" />
              <RateBar label="Recall" value={(result.recall ?? 0) * 100} color="#10b981" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-2">
            <Metric label="Matched" value={String(result.tp)} />
            <Metric label="Unmatched" value={String(result.fp)} />
            <Metric label="Missed" value={String(result.fn)} />
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <div className="flex items-start gap-3 rounded-2xl border border-separator-border bg-background-secondary-default p-3">
              <RiFocus3Line className="mt-0.5 size-5 shrink-0 text-status-yellow-text" aria-hidden />
              <div>
                <p className="text-body-2-medium text-text-primary">Sample coverage</p>
                <p className="mt-0.5 text-body-2-regular text-text-secondary">{result.clicks} trees marked in {result.patch_area_ha?.toFixed(2)} ha.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-2xl border border-separator-border bg-background-secondary-default p-3">
              <RiPlantLine className="mt-0.5 size-5 shrink-0 text-status-lime-text" aria-hidden />
              <div>
                <p className="text-body-2-medium text-text-primary">Adjusted estimate</p>
                <p className="mt-0.5 text-body-2-regular text-text-secondary">About {result.corrected_count ?? "n/a"} trees across the full area.</p>
              </div>
            </div>
          </div>
          {result.local_model && (
            <div className="rounded-2xl border border-status-blue-background bg-status-blue-background p-4">
              <p className="text-body-medium text-status-blue-text">Local calibration model</p>
              {result.local_model.available ? (
                <>
                  <p className="mt-1 text-title-2-medium text-status-blue-text tabular-nums">
                    {result.local_model.estimated_count} trees · {result.local_model.estimated_range?.[0]}–{result.local_model.estimated_range?.[1]}
                  </p>
                  <p className="mt-1 text-body-2-regular text-status-blue-text">
                    Trained from {result.local_model.training_examples} local detections. {result.local_model.note}
                  </p>
                </>
              ) : (
                <p className="mt-1 text-body-2-regular text-status-blue-text">{result.local_model.reason}</p>
              )}
            </div>
          )}
          {result.caveat && (
            <div className="rounded-2xl bg-status-yellow-background p-4">
              <p className="text-body-2-medium text-status-yellow-text">Read this carefully</p>
              <p className="mt-1 line-clamp-3 text-body-2-regular text-status-yellow-text">{result.caveat}</p>
            </div>
          )}
          <Button variant="secondary" size="small" onClick={props.onRestart}>
            Validate another patch
          </Button>
        </>
      )}
    </div>
  );
}
