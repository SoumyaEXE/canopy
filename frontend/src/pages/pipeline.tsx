import { useEffect, useState } from "react";
import { RiArrowLeftSLine, RiArrowRightSLine, RiFlowChart, RiPlayFill, RiStopFill } from "@remixicon/react";
import { url } from "@/api/client";
import { IconButton } from "@/components/base/buttons/icon-button";
import { Slider } from "@/components/base/slider/slider";
import { EmptyState, KeyValue, Panel, PanelHeader } from "@/components/canopy/ui";
import type { JobResult } from "@/types";
import { cx } from "@/utils/cx";

const AUTOPLAY_MS = 2200;

/** Step-through view of every intermediate raster the run produced, so each number can be traced to a picture. */
export function PipelinePage({ result }: { result: JobResult }) {
  const stages = result.pipeline?.stages ?? [];
  const [i, setI] = useState(0);
  const [blend, setBlend] = useState(100);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    if (!playing || stages.length < 2) return;
    const t = setInterval(() => setI((v) => (v + 1) % stages.length), AUTOPLAY_MS);
    return () => clearInterval(t);
  }, [playing, stages.length]);

  if (!stages.length) {
    return (
      <Panel className="min-h-[360px]">
        <EmptyState icon={RiFlowChart} title="No pipeline images for this run">
          Runs made before the pipeline view was added do not store intermediate images. Run the analysis again to see every stage.
        </EmptyState>
      </Panel>
    );
  }

  const stage = stages[Math.min(i, stages.length - 1)];
  const step = (d: number) => {
    setPlaying(false);
    setI((v) => (v + d + stages.length) % stages.length);
  };

  return (
    <div className="grid min-h-full grid-cols-1 gap-4 xl:grid-cols-12">
      <Panel className="gap-3 xl:col-span-3">
        <PanelHeader
          eyebrow={`Detector: ${result.pipeline?.detector_label ?? "classical"}`}
          title="Pipeline"
          icon={RiFlowChart}
          action={
            <IconButton
              icon={playing ? RiStopFill : RiPlayFill}
              aria-label={playing ? "Stop walkthrough" : "Play walkthrough"}
              onClick={() => setPlaying((v) => !v)}
            />
          }
        />
        <ol className="flex flex-col">
          {stages.map((s, n) => (
            <li key={s.key}>
              <button
                type="button"
                onClick={() => {
                  setPlaying(false);
                  setI(n);
                }}
                className={cx(
                  "flex w-full cursor-pointer items-start gap-3 rounded-xl px-2 py-2.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring",
                  n === i ? "bg-background-secondary-default" : "hover:bg-background-primary-hover",
                )}
              >
                <span
                  className={cx(
                    "flex size-6 shrink-0 items-center justify-center rounded-full text-caption-1-medium tabular-nums",
                    n === i ? "bg-text-primary text-background-primary-default" : n < i ? "bg-background-tertiary-default text-text-primary" : "border border-separator-border text-text-tertiary",
                  )}
                >
                  {n + 1}
                </span>
                <span className="min-w-0">
                  <span className={cx("block text-body-2-medium", n === i ? "text-text-primary" : "text-text-secondary")}>{s.title}</span>
                  {s.headline && <span className="block truncate text-caption-1-regular text-text-tertiary">{s.headline}</span>}
                </span>
              </button>
            </li>
          ))}
        </ol>
      </Panel>

      <div className="flex flex-col gap-4 xl:col-span-9">
        <Panel className="gap-4">
          <PanelHeader
            eyebrow={`Stage ${i + 1} of ${stages.length}`}
            title={stage.title}
            action={
              <div className="flex items-center gap-1">
                <IconButton icon={RiArrowLeftSLine} aria-label="Previous stage" onClick={() => step(-1)} />
                <IconButton icon={RiArrowRightSLine} aria-label="Next stage" onClick={() => step(1)} />
              </div>
            }
          />
          <div className="relative overflow-hidden rounded-xl border border-separator-border bg-black">
            <img src={url(result.imagery_png_url)} alt="" aria-hidden className="block max-h-[62vh] w-full object-contain" style={{ imageRendering: "pixelated" }} />
            <img
              key={stage.key}
              src={url(stage.url)}
              alt={stage.title}
              className="absolute inset-0 size-full object-contain transition-opacity duration-300"
              style={{ opacity: blend / 100, imageRendering: "pixelated" }}
            />
          </div>
          <Slider
            label="Stage output over imagery"
            minValue={0}
            maxValue={100}
            step={5}
            value={blend}
            onChange={setBlend}
            formatValue={(v) => `${v}%`}
            thumbLabel="Stage output opacity"
            showTooltip={false}
          />
        </Panel>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Panel className="gap-2">
            <PanelHeader eyebrow="What happens here" title="Method" />
            <p className="text-body-2-regular text-text-secondary">{stage.caption}</p>
          </Panel>
          <Panel className="gap-1">
            <PanelHeader eyebrow="Recorded in manifest.json" title="Numbers at this stage" className="mb-1" />
            <dl className="flex flex-col">
              {Object.entries(stage.stats).map(([k, v]) => (
                <KeyValue key={k} k={k} v={<span className="tabular-nums">{String(v)}</span>} />
              ))}
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}
