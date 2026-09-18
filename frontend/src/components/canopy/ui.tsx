import { useId, type ComponentType, type ReactNode } from "react";
import { RiArrowRightDownLine, RiArrowRightUpLine, RiSubtractLine } from "@remixicon/react";
import { Area, AreaChart, ResponsiveContainer, YAxis } from "recharts";
import { cx } from "@/utils/cx";

type IconComponent = ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;

/** Dashboard surface: white card, hairline border. */
export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <section
      className={cx(
        "flex min-w-0 flex-col rounded-2xl border border-separator-border bg-background-primary-default p-5",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  eyebrow,
  icon: Icon,
  action,
  className,
}: {
  title: ReactNode;
  eyebrow?: ReactNode;
  icon?: IconComponent;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex items-start justify-between gap-3", className)}>
      <div className="min-w-0">
        {eyebrow && <p className="text-caption-1-regular text-text-tertiary">{eyebrow}</p>}
        <h3 className={cx("flex items-center gap-2 font-display text-[17px] font-normal tracking-[-0.02em] text-text-primary", eyebrow && "mt-0.5")}>
          {Icon && <Icon className="size-4 shrink-0 text-foreground-icon-tertiary" aria-hidden />}
          {title}
        </h3>
      </div>
      {action}
    </div>
  );
}

/** A small coloured dot before a quiet label, the KPI label style. */
export function DotLabel({ color, children }: { color: string; children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 text-body-2-regular text-text-secondary">
      <span className="size-1.5 shrink-0 rounded-full" style={{ background: color }} />
      {children}
    </p>
  );
}

/** Headline figure: thin display numerals with a quiet unit below or beside. */
export function Figure({
  value,
  unit,
  size = "lg",
  unitBelow = false,
  className,
}: {
  value: ReactNode;
  unit?: ReactNode;
  size?: "xl" | "lg" | "md" | "sm";
  unitBelow?: boolean;
  className?: string;
}) {
  return (
    <div className={cx(unitBelow ? "flex flex-col gap-1" : "flex items-baseline gap-1.5", "whitespace-nowrap text-text-primary", className)}>
      <span
        className={cx(
          "font-display leading-none font-light",
          size === "xl" && "text-[52px]",
          size === "lg" && "text-[40px]",
          size === "md" && "text-[28px]",
          size === "sm" && "text-[20px] font-normal",
        )}
      >
        {value}
      </span>
      {unit && <span className="text-caption-1-medium text-text-tertiary">{unit}</span>}
    </div>
  );
}

/** Change against the previous run. Direction only, never good or bad: more crowns is not "better". */
export function Delta({ value, suffix = "", title }: { value: number | null; suffix?: string; title?: string }) {
  if (value == null || !Number.isFinite(value)) return null;
  const flat = Math.abs(value) < 0.05;
  const Icon = flat ? RiSubtractLine : value > 0 ? RiArrowRightUpLine : RiArrowRightDownLine;
  return (
    <span
      title={title}
      className="inline-flex items-center gap-0.5 rounded-md bg-background-secondary-default px-1.5 py-0.5 text-caption-1-medium text-text-secondary tabular-nums"
    >
      <Icon className="size-3.5" aria-hidden />
      {flat ? "0" : Math.abs(value).toFixed(Math.abs(value) < 10 ? 1 : 0)}
      {suffix}
    </span>
  );
}

/** Halftone area sparkline: dotted fill fading down, a crisp top line. */
export function Sparkline({ data, color, className }: { data: number[]; color: string; className?: string }) {
  const id = useId().replace(/:/g, "");
  // Two points are a line, not a trend; wait for a third run.
  if (data.length < 3) return null;
  const rows = data.map((v, i) => ({ i, v }));
  return (
    <div className={cx("h-12 w-28", className)} aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={rows} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <pattern id={`dots-${id}`} width="3" height="3" patternUnits="userSpaceOnUse">
              <circle cx="1.5" cy="1.5" r="0.75" fill={color} />
            </pattern>
            <linearGradient id={`fade-${id}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-background-primary-default)" stopOpacity={0} />
              <stop offset="100%" stopColor="var(--color-background-primary-default)" stopOpacity={0.95} />
            </linearGradient>
          </defs>
          <YAxis hide domain={["dataMin", "dataMax"]} />
          <Area type="monotone" dataKey="v" stroke="none" fill={`url(#dots-${id})`} isAnimationActive={false} />
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={`url(#fade-${id})`} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Segmented bar: filled ticks for the share, muted ticks for the rest. */
export function TickMeter({
  value,
  color,
  className,
  height = "h-7",
  label,
}: {
  value: number;
  color: string;
  className?: string;
  height?: string;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={label} className={cx("relative w-full", height, className)}>
      <div className="tick-meter absolute inset-0 text-neutral-200 dark:text-neutral-700" />
      <div
        className="tick-meter absolute inset-y-0 left-0 transition-[width] duration-500 ease-out"
        style={{ width: `${pct}%`, ["--tick-color" as string]: color }}
      />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-lg", className)} aria-hidden />;
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon: IconComponent;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex flex-1 flex-col items-center justify-center gap-2 px-6 py-4 text-center", className)}>
      <span className="flex size-10 items-center justify-center rounded-full bg-background-secondary-default">
        <Icon className="size-5 text-foreground-icon-secondary" aria-hidden />
      </span>
      <p className="text-body-medium text-text-primary">{title}</p>
      {children && <p className="max-w-[340px] text-body-2-regular text-text-tertiary">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function KeyValue({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-separator-border py-2.5 last:border-b-0">
      <dt className="shrink-0 text-body-2-regular text-text-tertiary">{k}</dt>
      <dd className="min-w-0 text-right text-body-2-medium break-words text-text-primary">{v}</dd>
    </div>
  );
}

export function formatRelative(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const SOURCE_LABEL: Record<string, string> = {
  geotiff: "GeoTIFF",
  image: "Image",
  kml: "KML",
  kmz: "KMZ",
  geojson: "GeoJSON",
  drawn: "Drawn area",
};
