import { useEffect, useRef, useState } from "react";
import { RiMapPin2Line, RiSearchLine } from "@remixicon/react";
import { Input } from "@/components/base/input/input";
import { cx } from "@/utils/cx";

type LngLat = [number, number];

interface Place {
  id: string;
  label: string;
  detail: string;
  center: LngLat;
  bounds: [LngLat, LngLat];
}

/**
 * Place search via OpenStreetMap Nominatim. Its usage policy allows light interactive use with
 * attribution: requests are debounced, at most one in flight, and only after three characters.
 */
export function PlaceSearch({ onSelect, className }: { onSelect: (place: Place) => void; className?: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Place[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 3) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      controller.current?.abort();
      const ac = new AbortController();
      controller.current = ac;
      setLoading(true);
      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=6&q=${encodeURIComponent(q)}`, {
          signal: ac.signal,
          headers: { Accept: "application/json" },
        });
        const rows = (await res.json()) as { place_id: number; display_name: string; lat: string; lon: string; boundingbox: string[]; type: string }[];
        setResults(
          rows.map((r) => {
            const [s, n, w, e] = r.boundingbox.map(Number);
            const [first, ...rest] = r.display_name.split(", ");
            return { id: String(r.place_id), label: first, detail: rest.slice(0, 3).join(", "), center: [Number(r.lon), Number(r.lat)], bounds: [[w, s], [e, n]] };
          }),
        );
        setOpen(true);
      } catch {
        /* aborted or offline: keep previous results */
      } finally {
        setLoading(false);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div className={cx("relative", className)}>
      <Input
        placeholder="Search a place or coordinates"
        aria-label="Search a place"
        leadingIcon={RiSearchLine}
        size="small"
        value={query}
        onChange={(v) => {
          setQuery(v);
          setOpen(true);
        }}
        fieldClassName="bg-background-primary-default shadow-dropdown"
      />
      {open && query.trim().length >= 3 && (
        <div className="absolute inset-x-0 top-full z-20 mt-1.5 overflow-hidden rounded-xl border border-separator-border bg-background-primary-default shadow-dropdown">
          {loading && !results.length ? (
            <p className="px-3 py-2.5 text-body-2-regular text-text-tertiary">Searching…</p>
          ) : results.length ? (
            <ul className="flex flex-col p-1">
              {results.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(r);
                      setOpen(false);
                      setQuery(r.label);
                    }}
                    className="flex w-full cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 text-left hover:bg-background-secondary-hover"
                  >
                    <RiMapPin2Line className="mt-0.5 size-4 shrink-0 text-foreground-icon-secondary" aria-hidden />
                    <span className="min-w-0">
                      <span className="block truncate text-body-2-medium text-text-primary">{r.label}</span>
                      <span className="block truncate text-caption-1-regular text-text-tertiary">{r.detail}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-2.5 text-body-2-regular text-text-tertiary">No places found.</p>
          )}
          <p className="border-t border-separator-border px-3 py-1.5 text-caption-2-regular text-text-tertiary">Search © OpenStreetMap contributors</p>
        </div>
      )}
    </div>
  );
}
