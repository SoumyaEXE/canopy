import { useEffect, useState } from "react";
import { RiLeafLine } from "@remixicon/react";
import { url } from "@/api/client";
import { Panel } from "@/components/canopy/ui";

interface Item {
  title: string;
  body: string;
}

/** Parses the backend's LIMITATIONS.md ("**Title.** body" paragraphs), the one source of this text. */
function parse(md: string): Item[] {
  return md
    .split(/\n\s*\n/)
    .map((para) => para.trim())
    .map((para) => para.match(/^\*\*(.+?)\*\*\s*([\s\S]*)$/))
    .filter((m): m is RegExpMatchArray => !!m)
    .map((m) => ({ title: m[1].replace(/\.$/, ""), body: m[2].trim() }));
}

export function LimitationsPanel() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(url("/api/limitations"))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => alive && setItems(parse(text)))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed) {
    return (
      <Panel>
        <p className="text-body-regular text-text-secondary">
          The limitations could not be loaded from the server. They are also in docs/LIMITATIONS.md in the repository.
        </p>
      </Panel>
    );
  }
  if (!items) return <p className="text-body-regular text-text-tertiary">Loading…</p>;

  const carbon = items.find((i) => i.title.toLowerCase().startsWith("no carbon"));
  const rest = items.filter((i) => i !== carbon);

  return (
    <div className="grid min-h-full grid-cols-1 gap-4 xl:grid-cols-12">
      {carbon && (
        <section className="flex flex-col gap-4 rounded-2xl bg-neutral-950 p-7 text-white xl:col-span-4 xl:row-span-2 dark:bg-brand dark:text-brand-foreground">
          <span className="flex size-10 items-center justify-center rounded-full bg-brand text-brand-foreground dark:bg-brand-foreground dark:text-brand">
            <RiLeafLine className="size-5" aria-hidden />
          </span>
          <h2 className="font-display text-[30px] leading-[1.1]">Why this tool does not estimate carbon</h2>
          <p className="text-body-regular text-white/70 dark:text-brand-foreground/75">{carbon.body}</p>
          <p className="mt-auto text-body-regular text-white/70 dark:text-brand-foreground/75">
            A carbon figure built on these outputs would inherit every error listed here, add the uncertainty of the conversion, and look far
            more precise than it is.
          </p>
        </section>
      )}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:col-span-8 xl:row-span-2">
        {rest.map((item, i) => (
          <Panel key={item.title} className="gap-2">
            <span className="font-display text-[13px] text-text-tertiary">{String(i + 1).padStart(2, "0")}</span>
            <p className="text-body-medium text-text-primary">{item.title}</p>
            <p className="text-body-2-regular text-text-secondary">{item.body}</p>
          </Panel>
        ))}
      </div>
    </div>
  );
}
