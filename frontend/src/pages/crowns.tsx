import { useMemo, useState } from "react";
import type { SortDescriptor } from "react-aria-components";
import { RiMapPin2Line, RiPlantLine } from "@remixicon/react";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { Pagination } from "@/components/base/pagination/pagination";
import { PillTab, PillTabList } from "@/components/base/tabs/pill-tab";
import { Table, TableBody, TableCell, TableColumn, TableHeader, TableRow } from "@/components/base/table/table";
import { EmptyState, Figure, KeyValue, Panel, PanelHeader, TickMeter } from "@/components/canopy/ui";
import { CONFIDENCE_COLORS } from "@/lib/mapStyle";
import type { ConfidenceBucket, CrownProps } from "@/types";

type Filter = "all" | ConfidenceBucket | "edge" | "rejected";

interface RejectedProps {
  id: number;
  area_m2: number;
  reason: "too_small" | "too_large" | "low_solidity";
  centroid_lonlat: [number, number];
}

const PAGE_SIZE = 25;
const BUCKET_CHIP = { high: "lime", medium: "yellow", low: "rose" } as const;
const REASON = { too_small: "Too small", too_large: "Too large", low_solidity: "Irregular shape" } as const;
const HEIGHT_REASON: Record<string, string> = {
  unavailable: "Not measured for this image",
  sun_angle: "Sun angle outside the usable range",
  occluded: "Shadow falls on another crown",
  no_shadow: "No usable shadow found",
  too_short: "Shadow too short to measure",
  implausible_height: "Outside 1–80 m, discarded",
};

interface CrownsPageProps {
  crowns: GeoJSON.FeatureCollection | null;
  rejected: GeoJSON.FeatureCollection | null;
  heightEnabled: boolean;
  onShowOnMap: (lngLat: [number, number], crownId?: number) => void;
}

export function CrownsPage({ crowns, rejected, heightEnabled, onShowOnMap }: CrownsPageProps) {
  const rows = useMemo(() => (crowns?.features ?? []).map((f) => f.properties as CrownProps), [crowns]);
  const rejectedRows = useMemo(() => (rejected?.features ?? []).map((f) => f.properties as RejectedProps), [rejected]);
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortDescriptor>({ column: "id", direction: "ascending" });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const counts = {
    all: rows.length,
    high: rows.filter((r) => r.confidence_bucket === "high").length,
    medium: rows.filter((r) => r.confidence_bucket === "medium").length,
    low: rows.filter((r) => r.confidence_bucket === "low").length,
    edge: rows.filter((r) => r.touches_edge).length,
    rejected: rejectedRows.length,
  };

  const filtered = useMemo(() => {
    const list = rows.filter((r) =>
      filter === "all" ? true : filter === "edge" ? r.touches_edge : filter === "rejected" ? false : r.confidence_bucket === filter,
    );
    const key = String(sort.column) as keyof CrownProps;
    const dir = sort.direction === "descending" ? -1 : 1;
    return [...list].sort((a, b) => {
      const av = (a[key] ?? -Infinity) as number;
      const bv = (b[key] ?? -Infinity) as number;
      return av === bv ? a.id - b.id : av > bv ? dir : -dir;
    });
  }, [rows, filter, sort]);

  const source = filter === "rejected" ? rejectedRows : filtered;
  const totalPages = Math.max(1, Math.ceil(source.length / PAGE_SIZE));
  const current = Math.min(page, totalPages);
  const pageRows = source.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);
  const selected = rows.find((r) => r.id === selectedId) ?? null;

  const tabs: { key: Filter; label: string }[] = [
    { key: "all", label: `All ${counts.all}` },
    { key: "high", label: `High ${counts.high}` },
    { key: "medium", label: `Medium ${counts.medium}` },
    { key: "low", label: `Low ${counts.low}` },
    { key: "edge", label: `Edge ${counts.edge}` },
    { key: "rejected", label: `Rejected ${counts.rejected}` },
  ];

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px] xl:grid-rows-[minmax(0,1fr)]">
      <Panel className="min-h-0 gap-4 p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
          <div className="overflow-x-auto">
            <PillTabList>
              {tabs.map((t) => (
                <PillTab
                  key={t.key}
                  variant="gray"
                  isSelected={filter === t.key}
                  onSelect={() => {
                    setFilter(t.key);
                    setPage(1);
                  }}
                >
                  {t.label}
                </PillTab>
              ))}
            </PillTabList>
          </div>
          <p className="text-body-2-regular text-text-tertiary tabular-nums">
            {source.length ? `${(current - 1) * PAGE_SIZE + 1}–${Math.min(current * PAGE_SIZE, source.length)} of ${source.length}` : "0 rows"}
          </p>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {filter === "rejected" ? (
            <Table aria-label="Rejected regions" size="sm">
              <TableHeader>
                <TableColumn isRowHeader>ID</TableColumn>
                <TableColumn>Reason</TableColumn>
                <TableColumn>Area</TableColumn>
                <TableColumn>Centroid</TableColumn>
                <TableColumn> </TableColumn>
              </TableHeader>
              <TableBody items={pageRows as RejectedProps[]}>
                {(r) => (
                  <TableRow id={`r${r.id}`}>
                    <TableCell>#{r.id}</TableCell>
                    <TableCell>{REASON[r.reason]}</TableCell>
                    <TableCell className="tabular-nums">{r.area_m2.toFixed(1)} m²</TableCell>
                    <TableCell className="text-text-tertiary tabular-nums">
                      {r.centroid_lonlat[1].toFixed(5)}, {r.centroid_lonlat[0].toFixed(5)}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="xs" leadingIcon={RiMapPin2Line} onClick={() => onShowOnMap(r.centroid_lonlat)}>
                        Map
                      </Button>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          ) : (
            <Table
              aria-label="Detected crowns"
              size="sm"
              selectionMode="single"
              selectedKeys={selectedId != null ? [selectedId] : []}
              onSelectionChange={(keys) => {
                const k = keys === "all" ? null : [...keys][0];
                setSelectedId(k == null ? null : Number(k));
              }}
              sortDescriptor={sort}
              onSortChange={setSort}
            >
              <TableHeader>
                <TableColumn id="id" isRowHeader allowsSorting>ID</TableColumn>
                <TableColumn id="confidence" allowsSorting>Confidence</TableColumn>
                <TableColumn id="area_m2" allowsSorting>Area</TableColumn>
                <TableColumn id="equivalent_diameter_m" allowsSorting>Diameter</TableColumn>
                <TableColumn id="height_m" allowsSorting>Height</TableColumn>
                <TableColumn id="solidity" allowsSorting>Solidity</TableColumn>
                <TableColumn>Edge</TableColumn>
              </TableHeader>
              <TableBody items={pageRows as CrownProps[]}>
                {(r) => (
                  <TableRow id={r.id} className="cursor-pointer data-[hovered]:bg-background-secondary-default data-[selected]:bg-background-secondary-hover">
                    <TableCell>#{r.id}</TableCell>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <Chip variant="caption" color={BUCKET_CHIP[r.confidence_bucket]}>
                          {r.confidence_bucket}
                        </Chip>
                        <span className="tabular-nums text-text-secondary">{r.confidence.toFixed(2)}</span>
                      </span>
                    </TableCell>
                    <TableCell className="tabular-nums">{r.area_m2.toFixed(1)} m²</TableCell>
                    <TableCell className="tabular-nums">{r.equivalent_diameter_m.toFixed(1)} m</TableCell>
                    <TableCell className="tabular-nums">{r.height_m != null ? `${r.height_m.toFixed(1)} m` : <span className="text-text-tertiary">—</span>}</TableCell>
                    <TableCell className="tabular-nums">{r.solidity.toFixed(2)}</TableCell>
                    <TableCell>{r.touches_edge ? <Chip variant="caption" color="soft">edge</Chip> : <span className="text-text-tertiary">—</span>}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </div>

        <div className="flex justify-center border-t border-separator-border px-5 py-3">
          <Pagination page={current} totalPages={totalPages} onChange={setPage} />
        </div>
      </Panel>

      <Panel className="min-h-0 gap-4 overflow-y-auto">
        {selected ? (
          <>
            <PanelHeader
              title={`Crown #${selected.id}`}
              icon={RiPlantLine}
              action={
                <Chip variant="caption" color={BUCKET_CHIP[selected.confidence_bucket]}>
                  {selected.confidence_bucket} {selected.confidence.toFixed(2)}
                </Chip>
              }
            />
            <div className="flex items-end gap-6">
              <Figure value={selected.area_m2.toFixed(1)} unit="m²" size="md" />
              <Figure value={selected.equivalent_diameter_m.toFixed(1)} unit="m ⌀" size="md" />
            </div>
            {selected.low_confidence_reason && (
              <p className="rounded-xl bg-status-rose-background px-3 py-2.5 text-body-2-regular text-status-rose-text">
                {selected.low_confidence_reason}
              </p>
            )}
            <div className="flex flex-col gap-3">
              {(["shape", "size", "separation", "shadow"] as const).map((k) => (
                <div key={k} className="grid grid-cols-[84px_1fr_40px] items-center gap-3">
                  <span className="text-body-2-medium text-text-secondary">{k === "size" ? "Size fit" : k[0].toUpperCase() + k.slice(1)}</span>
                  <TickMeter
                    value={k === "shadow" && !heightEnabled ? 0 : selected.signals[k]}
                    color={CONFIDENCE_COLORS[selected.confidence_bucket]}
                    height="h-3.5"
                    label={k}
                  />
                  <span className="text-right text-body-2-medium tabular-nums">
                    {k === "shadow" && !heightEnabled ? "n/a" : selected.signals[k].toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
            <dl>
              <KeyValue k="Height" v={selected.height_m != null ? `${selected.height_m.toFixed(1)} m (shadow-derived)` : HEIGHT_REASON[selected.height_reason ?? "unavailable"]} />
              <KeyValue k="Perimeter" v={`${selected.perimeter_m.toFixed(1)} m`} />
              <KeyValue k="Solidity" v={selected.solidity.toFixed(2)} />
              <KeyValue k="Boundary" v={selected.touches_edge ? "Touches the area edge, area truncated" : "Fully inside"} />
              <KeyValue k="Centroid" v={`${selected.centroid_lonlat[1].toFixed(6)}, ${selected.centroid_lonlat[0].toFixed(6)}`} />
            </dl>
            <Button variant="secondary" size="medium" leadingIcon={RiMapPin2Line} className="mt-auto w-full" onClick={() => onShowOnMap(selected.centroid_lonlat, selected.id)}>
              Show on map
            </Button>
          </>
        ) : (
          <EmptyState icon={RiPlantLine} title="Select a crown">
            Pick a row to see its measurements and the four signals behind its confidence score.
          </EmptyState>
        )}
      </Panel>
    </div>
  );
}
