import { useEffect, useState, type ReactNode } from "react";
import { Sidebar, type NavGroup } from "@/components/canopy/sidebar";
import { cx } from "@/utils/cx";

export function useMedia(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/**
 * App frame: collapsible rail, top bar, content. Wide pages (map, table) collapse the rail to icons
 * automatically; the user's toggle wins until they navigate elsewhere.
 */
export function Shell<K extends string>({
  groups,
  selected,
  onSelect,
  wide = false,
  header,
  children,
}: {
  groups: NavGroup<K>[];
  selected: K | null;
  onSelect: (key: K) => void;
  wide?: boolean;
  header: ReactNode;
  children: ReactNode;
}) {
  const isWideScreen = useMedia("(min-width: 1440px)");
  const isPhone = !useMedia("(min-width: 768px)");
  const [manual, setManual] = useState<boolean | null>(null);
  useEffect(() => setManual(null), [selected]);
  const collapsed = manual ?? (wide || !isWideScreen);

  return (
    <div className="fixed inset-0 flex bg-background-full text-text-primary">
      {!isPhone && (
        <Sidebar
          groups={groups}
          selected={selected}
          onSelect={onSelect}
          collapsed={collapsed}
          onToggleCollapsed={() => setManual(!collapsed)}
          footer={
            <div className="rounded-xl bg-background-secondary-default p-3">
              <p className="text-caption-1-medium text-text-primary">Classical CV, no carbon</p>
              <p className="mt-0.5 text-caption-1-regular text-text-tertiary">Every number ships with its provenance.</p>
            </div>
          }
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        {header}
        <main className={cx("relative min-h-0 flex-1", isPhone && "pb-16")}>{children}</main>
      </div>
      {isPhone && (
        <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-30 flex h-16 items-stretch overflow-x-auto border-t border-separator-border bg-background-primary-default px-1">
          {groups.flatMap((g) => g.entries).map((entry) => (
            <button
              key={entry.key}
              type="button"
              onClick={() => onSelect(entry.key)}
              aria-current={selected === entry.key ? "page" : undefined}
              className={cx(
                "flex min-w-16 flex-1 cursor-pointer flex-col items-center justify-center gap-1 text-caption-2-medium",
                selected === entry.key ? "text-text-primary" : "text-text-tertiary",
              )}
            >
              <span className={cx("flex h-7 w-11 items-center justify-center rounded-full", selected === entry.key && "bg-brand text-brand-foreground")}>
                <entry.icon className="size-5" aria-hidden />
              </span>
              {entry.label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}

export function TopBar({ title, eyebrow, meta, actions }: { title: ReactNode; eyebrow?: ReactNode; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex min-h-[76px] shrink-0 items-center gap-3 border-b border-separator-border bg-background-primary-default px-4 py-3 md:px-6">
      <div className="mr-auto min-w-0">
        {eyebrow && <div className="mb-1 flex items-center gap-1.5 text-caption-1-regular text-text-tertiary">{eyebrow}</div>}
        <h1 className="truncate font-display text-[24px] leading-none font-normal tracking-[-0.03em] text-text-primary">{title}</h1>
        {meta && <div className="mt-1.5 hidden items-center gap-2 text-caption-1-regular text-text-tertiary md:flex">{meta}</div>}
      </div>
      {actions}
    </header>
  );
}
