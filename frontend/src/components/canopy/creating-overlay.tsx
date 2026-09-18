import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { RiCheckLine } from "@remixicon/react";
import { cx } from "@/utils/cx";

export type CreatingState = { name: string; source: "file" | "area" | "sample"; phase: "working" | "done" } | null;

const STEPS: Record<"file" | "area" | "sample", string[]> = {
  file: ["Reading the file", "Checking the boundary", "Creating the workspace", "Queuing the first analysis"],
  area: ["Checking the boundary", "Measuring the area", "Creating the workspace", "Queuing the first analysis"],
  sample: ["Copying the sample", "Creating the workspace", "Loading the result"],
};
const STEP_MS = 520;

/** A folder that sprouts trees while the workspace is created. */
function GrowingFolder({ done }: { done: boolean }) {
  const trees = [
    { x: 38, h: 26, d: 0.15 },
    { x: 60, h: 36, d: 0.35 },
    { x: 82, h: 22, d: 0.55 },
  ];
  return (
    <svg viewBox="0 0 120 110" className="h-28 w-32" aria-hidden>
      {/* back of the folder */}
      <motion.path
        d="M14 42 h30 l8 -9 h54 a6 6 0 0 1 6 6 v58 a6 6 0 0 1 -6 6 h-86 a6 6 0 0 1 -6 -6 z"
        className="fill-background-tertiary-default stroke-separator-border"
        strokeWidth={1.5}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
      />
      {/* trees growing out of it */}
      {trees.map((t, i) => (
        <motion.g key={i} initial={{ scaleY: 0, opacity: 0 }} animate={{ scaleY: 1, opacity: 1 }} transition={{ delay: t.d, type: "spring", stiffness: 180, damping: 14 }} style={{ originX: `${t.x}px`, originY: "70px", transformBox: "view-box" }}>
          <rect x={t.x - 1.5} y={70 - t.h * 0.45} width={3} height={t.h * 0.45} rx={1.5} fill="#65a30d" />
          <motion.circle
            cx={t.x}
            cy={70 - t.h * 0.55}
            r={t.h * 0.34}
            fill={i === 1 ? "#84cc16" : "#10b981"}
            animate={{ scale: [1, 1.06, 1] }}
            transition={{ delay: 0.8 + i * 0.2, duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            style={{ originX: `${t.x}px`, originY: `${70 - t.h * 0.55}px` }}
          />
        </motion.g>
      ))}
      {/* front flap, drawn over the trunks */}
      <motion.path
        d="M8 62 a6 6 0 0 1 6 -6 h92 a6 6 0 0 1 6 6 l-4 35 a6 6 0 0 1 -6 6 h-86 a6 6 0 0 1 -6 -6 z"
        className="fill-background-secondary-default stroke-separator-border"
        strokeWidth={1.5}
        initial={{ rotateX: 50, opacity: 0 }}
        animate={{ rotateX: 0, opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        style={{ transformOrigin: "60px 103px" }}
      />
      <AnimatePresence>
        {done && (
          <motion.g initial={{ scale: 0, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 300, damping: 16 }} style={{ originX: "60px", originY: "80px" }}>
            <circle cx={60} cy={80} r={11} fill="#b4e23c" />
            <path d="M55 80 l3.5 3.5 l6.5 -7" fill="none" stroke="#0f1a02" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
          </motion.g>
        )}
      </AnimatePresence>
    </svg>
  );
}

export function CreatingOverlay({ state }: { state: CreatingState }) {
  return (
    <AnimatePresence>
      {state && (
        <motion.div
          key="creating"
          className="fixed inset-0 z-[70] flex items-center justify-center bg-background-full/80 backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.25 } }}
          role="status"
          aria-live="polite"
        >
          <CreatingCard name={state.name} source={state.source} done={state.phase === "done"} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Mounted fresh for each creation, so the step counter always starts at zero. */
function CreatingCard({ name, source, done }: { name: string; source: "file" | "area" | "sample"; done: boolean }) {
  const steps = STEPS[source];
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (done) return;
    const t = setInterval(() => setStep((s) => Math.min(s + 1, steps.length - 1)), STEP_MS);
    return () => clearInterval(t);
  }, [done, steps.length]);
  const current = done ? steps.length : step;

  return (
    <motion.div
      className="flex w-[340px] flex-col items-center gap-5 rounded-2xl border border-separator-border bg-background-primary-default px-6 py-7 shadow-2xl"
      initial={{ y: 16, scale: 0.97 }}
      animate={{ y: 0, scale: 1 }}
      exit={{ y: 8, scale: 0.98 }}
      transition={{ type: "spring", stiffness: 320, damping: 28 }}
    >
      <GrowingFolder done={done} />
      <div className="text-center">
        <p className="text-[17px] font-medium tracking-[-0.01em] text-text-primary">{done ? "Workspace ready" : "Creating workspace"}</p>
        <p className="mt-0.5 max-w-[280px] truncate text-body-2-regular text-text-tertiary">{name}</p>
      </div>
      <ol className="flex w-full flex-col gap-2">
        {steps.map((s, i) => (
          <li key={s} className={cx("flex items-center gap-2.5 text-body-2-regular transition-colors duration-300", i <= current ? "text-text-primary" : "text-text-tertiary")}>
            <span className={cx("flex size-4 items-center justify-center rounded-full transition-colors duration-300", i < current ? "bg-brand text-brand-foreground" : i === current ? "border border-text-primary" : "border border-separator-border")}>
              {i < current ? <RiCheckLine className="size-3" aria-hidden /> : i === current ? <span className="size-1.5 animate-pulse rounded-full bg-text-primary" /> : null}
            </span>
            {s}
          </li>
        ))}
      </ol>
      <div className="h-1 w-full overflow-hidden rounded-full bg-background-secondary-default">
        <motion.div className="h-full rounded-full bg-brand" initial={{ width: "4%" }} animate={{ width: done ? "100%" : `${Math.min(92, ((step + 1) / (steps.length + 1)) * 100)}%` }} transition={{ ease: "easeOut", duration: 0.5 }} />
      </div>
    </motion.div>
  );
}
