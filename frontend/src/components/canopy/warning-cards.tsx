import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  RiAlertLine,
  RiArrowDownSLine,
  RiCpuLine,
  RiFocus3Line,
  RiForbid2Line,
  RiImageLine,
  RiInformationLine,
  RiLayoutGridLine,
  RiMapPin2Line,
  RiPlantLine,
  RiRulerLine,
  RiSunLine,
  RiZoomOutLine,
  type RemixiconComponentType,
} from "@remixicon/react";
import { cx } from "@/utils/cx";

type Tone = "info" | "caution";

interface Kind {
  test: RegExp;
  title: (w: string) => string;
  icon: RemixiconComponentType;
  tone: Tone;
}

const num = (w: string) => w.match(/^(\d[\d,]*)/)?.[1] ?? "";

/** Pipeline warnings are full sentences; each gets a short title, an icon and a tone. */
const KINDS: Kind[] = [
  {
    test: /no location/i,
    title: () => "No location in file",
    icon: RiMapPin2Line,
    tone: "info",
  },
  {
    test: /resolution was entered|was assumed/i,
    title: () => "Resolution assumed",
    icon: RiRulerLine,
    tone: "caution",
  },
  {
    test: /^Dense canopy/i,
    title: () => "Dense-canopy mode",
    icon: RiPlantLine,
    tone: "info",
  },
  {
    test: /threshold confidence|Otsu split/i,
    title: () => "Weak greenness split",
    icon: RiAlertLine,
    tone: "caution",
  },
  {
    test: /AI tree|trained AI|classical blob detection was used/i,
    title: () => "Classical detector used",
    icon: RiCpuLine,
    tone: "info",
  },
  {
    test: /rejected by size/i,
    title: (w) => `${num(w)} regions rejected`,
    icon: RiForbid2Line,
    tone: "info",
  },
  {
    test: /low confidence/i,
    title: (w) => `${num(w)} low-confidence crowns`,
    icon: RiFocus3Line,
    tone: "caution",
  },
  {
    test: /touch the area boundary/i,
    title: (w) => `${num(w)} crowns on the edge`,
    icon: RiLayoutGridLine,
    tone: "info",
  },
  {
    test: /Map data not yet available|no zoom \d+ imagery/i,
    title: () => "Zoom lowered: no imagery",
    icon: RiZoomOutLine,
    tone: "caution",
  },
  {
    test: /fetched at zoom/i,
    title: () => "Coarser zoom for a large area",
    icon: RiZoomOutLine,
    tone: "caution",
  },
  {
    test: /averaged\s+down|decimat/i,
    title: () => "Image downsampled",
    icon: RiImageLine,
    tone: "caution",
  },
  {
    test: /m per pixel\. Individual crowns/i,
    title: () => "Coarse imagery",
    icon: RiImageLine,
    tone: "caution",
  },
  {
    test: /latitude/i,
    title: () => "Pixel size varies",
    icon: RiRulerLine,
    tone: "info",
  },
  {
    test: /sun|acquisition|height/i,
    title: () => "Height not measured",
    icon: RiSunLine,
    tone: "info",
  },
];

export function describeWarning(w: string) {
  const k = KINDS.find((x) => x.test.test(w));
  if (k) return { title: k.title(w).trim(), icon: k.icon, tone: k.tone };
  const words = w
    .split(/\s+/)
    .slice(0, 5)
    .join(" ")
    .replace(/[.,:;]$/, "");
  return { title: words, icon: RiInformationLine, tone: "info" as Tone };
}

const TONE: Record<Tone, { icon: string; ring: string }> = {
  info: { icon: "bg-sky-500/12 text-sky-500", ring: "hover:ring-sky-500/30" },
  caution: {
    icon: "bg-amber-500/14 text-amber-500",
    ring: "hover:ring-amber-500/35",
  },
};

function WarningCard({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const d = describeWarning(text);
  const t = TONE[d.tone];
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={cx(
          "w-full cursor-pointer rounded-xl bg-background-secondary-default p-2.5 text-left ring-1 ring-separator-border transition-shadow ring-inset",
          t.ring,
        )}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={cx(
              "flex size-7 shrink-0 items-center justify-center rounded-lg",
              t.icon,
            )}
          >
            <d.icon className="size-4" aria-hidden />
          </span>
          <span className="min-w-0 flex-1 truncate text-body-2-medium text-text-primary">
            {d.title}
          </span>
          <RiArrowDownSLine
            className={cx(
              "size-4 shrink-0 text-text-tertiary transition-transform duration-200",
              open && "rotate-180",
            )}
            aria-hidden
          />
        </div>
        <AnimatePresence initial={false}>
          {open && (
            <motion.p
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden pl-9.5 text-caption-1-regular text-text-secondary"
            >
              <span className="block pt-1.5">{text}</span>
            </motion.p>
          )}
        </AnimatePresence>
      </button>
    </li>
  );
}

/** Warnings as compact cards: cautions first, click a card for the full explanation. */
export function WarningCards({
  warnings,
  className,
  header = true,
  listClassName,
}: {
  warnings: string[];
  className?: string;
  header?: boolean;
  listClassName?: string;
}) {
  const sorted = [...warnings].sort(
    (a, b) =>
      Number(describeWarning(b).tone === "caution") -
      Number(describeWarning(a).tone === "caution"),
  );
  const cautions = sorted.filter(
    (w) => describeWarning(w).tone === "caution",
  ).length;
  return (
    <div className={cx("flex flex-col gap-2", className)}>
      {header && (
        <div className="flex items-center gap-2">
          <span className="text-body-2-medium text-text-primary">Warnings</span>
          <span className="rounded-full bg-background-secondary-default px-1.5 text-caption-1-medium text-text-secondary tabular-nums ring-1 ring-separator-border ring-inset">
            {warnings.length}
          </span>
          {cautions > 0 && (
            <span className="ml-auto text-caption-1-regular text-amber-500">
              {cautions} to check
            </span>
          )}
        </div>
      )}
      <ul className={cx("flex flex-col gap-1.5", listClassName)}>
        {sorted.map((w) => (
          <WarningCard key={w} text={w} />
        ))}
      </ul>
    </div>
  );
}
