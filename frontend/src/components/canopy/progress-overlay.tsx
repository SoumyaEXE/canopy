import { RiCheckLine } from "@remixicon/react";
import { Button } from "@/components/base/buttons/button";
import type { JobStatus } from "@/types";
import { cx } from "@/utils/cx";

/** Named stages, not a spinner (spec 6.7). Non-blocking, so the previous result stays readable underneath. */
export function ProgressOverlay({ status, onCancel }: { status: JobStatus | null; onCancel?: () => void }) {
  const stages = status?.stages ?? [];
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-auto flex w-[320px] max-w-[calc(100vw-32px)] flex-col gap-3 rounded-2xl border border-border-button-default bg-background-primary-default p-4 shadow-dropdown"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-display text-[15px] text-text-primary">Running analysis</p>
        <span className="text-body-2-regular text-text-tertiary tabular-nums">{status ? `${status.elapsed_s.toFixed(1)}s` : "Submitting"}</span>
      </div>
      <ol className="flex flex-col gap-1.5">
        {stages.length === 0 && <li className="text-body-2-regular text-text-secondary">Sending the job to the server…</li>}
        {stages.map((stage) => {
          const done = stage.seconds != null;
          const running = !done && status?.stage === stage.name;
          return (
            <li key={stage.name} className="flex items-center gap-2.5">
              <span className="flex size-4 shrink-0 items-center justify-center">
                {done ? (
                  <RiCheckLine className="size-4 text-confidence-high" aria-hidden />
                ) : running ? (
                  <span className="size-2 animate-pulse rounded-full bg-accent-400" />
                ) : (
                  <span className="size-2 rounded-full border border-border-checkbox-default" />
                )}
              </span>
              <span
                className={cx(
                  "flex-1 text-body-2-medium",
                  done || running ? "text-text-primary" : "text-text-tertiary",
                )}
              >
                {stage.label}
              </span>
              <span className="text-body-2-regular text-text-tertiary tabular-nums">
                {done ? `${stage.seconds!.toFixed(1)}s` : running ? "running" : ""}
              </span>
            </li>
          );
        })}
      </ol>
      {onCancel && (
        <Button variant="ghost" size="small" onClick={onCancel} className="pointer-events-auto self-end">
          Stop waiting
        </Button>
      )}
    </div>
  );
}
