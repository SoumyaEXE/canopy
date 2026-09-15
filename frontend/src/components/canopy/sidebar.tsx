import type { ComponentType, ReactNode } from "react";
import { RiSideBarFill } from "@remixicon/react";
import { ThemeToggle } from "@/components/application/theme/theme-toggle";
import { cx } from "@/utils/cx";

type IconComponent = ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;

export interface NavEntry<K extends string> {
  key: K;
  label: string;
  icon: IconComponent;
  badge?: ReactNode;
  /** Something needs attention; shown as a dot when the rail is collapsed. */
  alert?: boolean;
}

/**
 * CANOPY's rail, on BoardUI's dashboard sidebar recipe: 248px expanded, 64px collapsed,
 * labels blur and shrink away while icons stay pinned so nothing jumps.
 */
function Collapsible({ collapsed, children, className }: { collapsed: boolean; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "flex min-w-0 items-center overflow-hidden transition-[max-width,opacity,filter] duration-300 ease-in-out",
        collapsed ? "max-w-0 opacity-0 blur-[3px]" : "max-w-full opacity-100 blur-0",
        className,
      )}
    >
      {children}
    </span>
  );
}

function NavButton<K extends string>({
  entry,
  selected,
  collapsed,
  onSelect,
}: {
  entry: NavEntry<K>;
  selected: boolean;
  collapsed: boolean;
  onSelect: (key: K) => void;
}) {
  const Icon = entry.icon;
  return (
    <button
      type="button"
      onClick={() => onSelect(entry.key)}
      aria-current={selected ? "page" : undefined}
      aria-label={entry.label}
      title={collapsed ? entry.label : undefined}
      className={cx(
        "group relative flex h-10 cursor-pointer items-center justify-between overflow-hidden rounded-xl px-2.5",
        "outline-none transition-[width,background-color,color] duration-300 ease-in-out focus-visible:ring-2 focus-visible:ring-border-focus-ring",
        collapsed ? "w-10" : "w-full",
        selected
          ? "bg-brand text-brand-foreground shadow-[inset_0_-1px_0_rgba(0,0,0,0.08)]"
          : "text-text-secondary hover:bg-background-secondary-hover hover:text-text-primary",
      )}
    >
      <span className="flex min-w-0 items-center gap-2.5">
        <Icon
          className={cx(
            "size-5 shrink-0 transition-colors",
            selected ? "text-brand-foreground" : "text-foreground-icon-secondary group-hover:text-foreground-icon-primary",
          )}
          aria-hidden
        />
        <Collapsible collapsed={collapsed}>
          <span className={cx("text-body-medium whitespace-nowrap", selected && "text-brand-foreground")}>{entry.label}</span>
        </Collapsible>
      </span>
      {entry.badge != null && (
        <Collapsible collapsed={collapsed}>
          <span
            className={cx(
              "rounded-md px-1.5 py-px text-caption-1-semibold tabular-nums",
              selected ? "bg-black/10 text-brand-foreground" : "bg-background-tertiary-default text-text-secondary",
            )}
          >
            {entry.badge}
          </span>
        </Collapsible>
      )}
      {collapsed && entry.alert && (
        <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-confidence-medium" aria-hidden />
      )}
    </button>
  );
}

export interface NavGroup<K extends string> {
  label: string;
  entries: NavEntry<K>[];
}

export function Sidebar<K extends string>({
  groups,
  selected,
  onSelect,
  collapsed,
  onToggleCollapsed,
  footer,
}: {
  groups: NavGroup<K>[];
  selected: K | null;
  onSelect: (key: K) => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  footer?: ReactNode;
}) {
  return (
    <aside
      className={cx(
        "flex h-full shrink-0 flex-col justify-between overflow-hidden border-r border-separator-border bg-background-primary-default",
        "transition-[width] duration-300 ease-in-out",
        collapsed ? "w-16 px-3 py-4" : "w-[248px] px-4 py-4",
      )}
    >
      <div className="flex min-h-0 flex-col gap-6">
        <div className={cx("flex items-center", collapsed ? "flex-col gap-4" : "justify-between")}>
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-neutral-950 dark:bg-brand">
              <svg viewBox="0 0 24 24" className="size-5 text-brand dark:text-brand-foreground" aria-hidden>
                <path fill="currentColor" d="M12 2 4 13h5l-3 5h5v4h2v-4h5l-3-5h5z" />
              </svg>
            </span>
            <Collapsible collapsed={collapsed}>
              <span className="font-brand text-[19px] leading-none tracking-[-0.03em] text-text-primary">canopy</span>
            </Collapsible>
          </div>
          <button
            type="button"
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            onClick={onToggleCollapsed}
            className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-foreground-icon-secondary outline-none transition-colors hover:bg-background-secondary-hover hover:text-foreground-icon-primary focus-visible:ring-2 focus-visible:ring-border-focus-ring"
          >
            <RiSideBarFill className={cx("size-5 transition-transform duration-300", !collapsed && "-scale-x-100")} aria-hidden />
          </button>
        </div>

        <nav aria-label="Main" className="flex min-h-0 flex-col gap-1 overflow-y-auto">
          {groups.map((group, gi) => (
            <div key={group.label} className="flex flex-col gap-1">
              {collapsed ? (
                gi > 0 && <div className="my-3 h-px w-10 bg-separator-border" />
              ) : (
                <span className={cx("truncate px-2.5 pb-1.5 text-caption-1-medium whitespace-nowrap text-text-tertiary", gi > 0 && "pt-5")}>{group.label}</span>
              )}
              {group.entries.map((entry) => (
                <NavButton key={entry.key} entry={entry} selected={selected === entry.key} collapsed={collapsed} onSelect={onSelect} />
              ))}
            </div>
          ))}
        </nav>
      </div>

      <div className="flex shrink-0 flex-col gap-3">
        {footer && !collapsed && footer}
        {collapsed ? <ThemeToggle collapsed /> : <ThemeToggle appearance="sidebar-segmented" />}
      </div>
    </aside>
  );
}
