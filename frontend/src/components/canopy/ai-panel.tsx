import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  RiAddLine,
  RiArrowUpLine,
  RiCloseLine,
  RiContractLeftRightLine,
  RiExpandLeftRightLine,
  RiKey2Line,
  RiLoader4Line,
  RiPlayFill,
  RiSearchLine,
  RiSparkling2Fill,
  RiStopFill,
} from "@remixicon/react";
import { api, CanopyApiError } from "@/api/client";
import { Button } from "@/components/base/buttons/button";
import { useMedia } from "@/components/canopy/shell";
import type { AssistantInfo, ChatTurn, JobParams } from "@/types";
import { cx } from "@/utils/cx";

type Action = { params: Partial<JobParams>; reason: string; applied?: boolean };
type Source = { n: number; title: string; url: string };
type Message = { id: string; role: "user" | "assistant"; text: string; actions?: Action[]; tools?: string[]; sources?: Source[]; error?: string; pending?: boolean };

const PARAM_LABEL: Record<string, string> = {
  detector: "Detector",
  min_crown_diameter_m: "Min crown diameter",
  veg_index: "Vegetation index",
  threshold_mode: "Threshold",
  threshold_manual: "Manual threshold",
  tile_zoom: "Tile zoom",
  enable_height: "Height",
};

function formatValue(k: string, v: unknown): string {
  if (k === "min_crown_diameter_m") return `${Number(v).toFixed(1)} m`;
  if (k === "detector") return v === "classical" ? "Classical" : "Auto";
  if (k === "veg_index") return String(v).toUpperCase();
  if (k === "enable_height") return v ? "on" : "off";
  return String(v);
}

const storageKey = (projectId: string) => `canopy:ai:${projectId}`;

function loadHistory(projectId: string): Message[] {
  try {
    const raw = localStorage.getItem(storageKey(projectId));
    const parsed = raw ? (JSON.parse(raw) as Message[]) : [];
    return parsed.filter((m) => !m.pending);
  } catch {
    return [];
  }
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning." : h < 18 ? "Good afternoon." : "Good evening.";
}

/* ------------------------------------------------------------------ minimal, safe markdown */

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const key = `${keyBase}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={key} className="font-semibold text-text-primary">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={key} className="rounded bg-background-secondary-default px-1 py-px font-mono text-[12.5px]">{t.slice(1, -1)}</code>);
    else out.push(<em key={key}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Markdown({ text }: { text: string }) {
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/);
  return (
    <div className="flex flex-col gap-2.5">
      {blocks.map((block, bi) => {
        const lines = block.split("\n").filter((l) => l.trim());
        if (!lines.length) return null;
        if (lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l))) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={bi} className={cx("flex flex-col gap-1 pl-5", ordered ? "list-decimal" : "list-disc", "marker:text-text-tertiary")}>
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, ""), `${bi}-${li}`)}</li>
              ))}
            </Tag>
          );
        }
        const h = /^(#{1,4})\s+(.*)$/.exec(lines[0]);
        if (h && lines.length === 1) return <p key={bi} className="text-body-medium text-text-primary">{inline(h[2], `${bi}`)}</p>;
        return (
          <p key={bi}>
            {lines.map((l, li) => (
              <span key={li}>
                {li > 0 && <br />}
                {inline(l.replace(/^#{1,4}\s+/, ""), `${bi}-${li}`)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ pieces */

/** The glowing orb on the empty state: two blurred gradients breathing out of phase. */
const SIZE_KEY = "canopy.ai.size";
const MIN_W = 360;
const MAX_W = 960;
const MIN_H = 420;
const NARROW = 420;
const WIDE = 720;
const GAP = 8;

type PanelSize = { w: number; h: number | null }; // h null = full height

function loadSize(): PanelSize {
  try {
    const v = JSON.parse(localStorage.getItem(SIZE_KEY) ?? "null");
    if (v && typeof v.w === "number") return { w: v.w, h: typeof v.h === "number" ? v.h : null };
  } catch {
    /* blocked storage: defaults */
  }
  return { w: NARROW, h: null };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/** Drag-to-resize for the floating panel: width from the left edge, height from the bottom edge. */
function usePanelSize() {
  const [size, setSize] = useState<PanelSize>(loadSize);
  const [dragging, setDragging] = useState<"w" | "h" | null>(null);
  useEffect(() => {
    try {
      localStorage.setItem(SIZE_KEY, JSON.stringify(size));
    } catch {
      /* ignore */
    }
  }, [size]);
  const start = useCallback(
    (axis: "w" | "h") => (e: ReactPointerEvent<HTMLDivElement>) => {
      e.preventDefault();
      const el = e.currentTarget;
      el.setPointerCapture(e.pointerId);
      setDragging(axis);
      const move = (ev: PointerEvent) =>
        setSize((s) =>
          axis === "w"
            ? { ...s, w: clamp(window.innerWidth - ev.clientX - GAP, MIN_W, Math.min(MAX_W, window.innerWidth - 96)) }
            : { ...s, h: clamp(ev.clientY - GAP, MIN_H, window.innerHeight - 2 * GAP) },
        );
      const up = () => {
        setDragging(null);
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        el.removeEventListener("pointercancel", up);
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
      el.addEventListener("pointercancel", up);
    },
    [],
  );
  return { size, setSize, dragging, start };
}

const BOX_KEY = "canopy.ai.composer";
const BOX_MIN = 40;
const BOX_DEFAULT = 56;
const BOX_MAX = 360;

/** Height of the message box, dragged from the grip above it and remembered. */
function useComposerHeight() {
  const [h, setH] = useState<number>(() => {
    try {
      const v = Number(localStorage.getItem(BOX_KEY));
      return v >= BOX_MIN && v <= BOX_MAX ? v : BOX_DEFAULT;
    } catch {
      return BOX_DEFAULT;
    }
  });
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    try {
      localStorage.setItem(BOX_KEY, String(h));
    } catch {
      /* ignore */
    }
  }, [h]);
  const start = (e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const el = e.currentTarget;
    el.setPointerCapture(e.pointerId);
    const y0 = e.clientY;
    const h0 = h;
    setDragging(true);
    const move = (ev: PointerEvent) => setH(clamp(h0 + (y0 - ev.clientY), BOX_MIN, Math.min(BOX_MAX, window.innerHeight * 0.45)));
    const up = () => {
      setDragging(false);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
    };
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };
  return { h, setH, dragging, start };
}

function Orb() {
  return (
    <div className="relative size-28" aria-hidden>
      <motion.div
        className="absolute inset-2 rounded-full blur-xl"
        style={{ background: "radial-gradient(circle at 35% 35%, #d9f99d, #84cc16 45%, #10b981 80%)" }}
        animate={{ scale: [1, 1.12, 1], opacity: [0.55, 0.8, 0.55] }}
        transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute inset-5 rounded-full"
        style={{ background: "radial-gradient(circle at 32% 28%, #f7fee7 0%, #bef264 30%, #65a30d 70%, #166534 100%)", boxShadow: "inset -8px -10px 24px rgba(0,0,0,0.25)" }}
        animate={{ y: [0, -5, 0], rotate: [0, 8, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute top-9 right-3 size-7 rounded-full"
        style={{ background: "radial-gradient(circle at 35% 30%, #ecfccb, #84cc16 70%)" }}
        animate={{ y: [0, 4, 0], x: [0, -2, 0] }}
        transition={{ duration: 3.4, repeat: Infinity, ease: "easeInOut", delay: 0.4 }}
      />
    </div>
  );
}

function ActionCard({ action, disabled, onApply }: { action: Action; disabled: boolean; onApply: () => void }) {
  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-separator-border bg-background-secondary-default">
      <div className="flex items-center gap-2 border-b border-separator-border px-3 py-2 text-caption-1-medium text-text-secondary">
        <RiSparkling2Fill className="size-3.5 text-brand" aria-hidden />
        Suggested re-run
      </div>
      <dl className="flex flex-col gap-1 px-3 py-2.5">
        {Object.entries(action.params).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 text-body-2-regular">
            <dt className="text-text-tertiary">{PARAM_LABEL[k] ?? k}</dt>
            <dd className="font-medium text-text-primary tabular-nums">{formatValue(k, v)}</dd>
          </div>
        ))}
      </dl>
      <p className="px-3 pb-2.5 text-caption-1-regular text-text-tertiary">{action.reason}</p>
      <div className="px-3 pb-3">
        <Button variant={action.applied ? "secondary" : "primary"} size="small" leadingIcon={RiPlayFill} disabled={disabled || action.applied} onClick={onApply} className="w-full">
          {action.applied ? "Run started" : "Apply and run"}
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ panel */

export function AiPanel({
  open,
  onClose,
  projectId,
  projectName,
  runId,
  running,
  onApplyParams,
}: {
  open: boolean;
  onClose: () => void;
  projectId: string;
  projectName: string;
  runId: string | null;
  running: boolean;
  onApplyParams: (params: Partial<JobParams>) => void;
}) {
  const [info, setInfo] = useState<AssistantInfo | null>(null);
  const [messages, setMessages] = useState<Message[]>(() => loadHistory(projectId));
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const { size, setSize, dragging, start } = usePanelSize();
  const box = useComposerHeight();
  const desktop = useMedia("(min-width: 768px)");
  const wide = size.w >= (NARROW + WIDE) / 2;
  const abort = useRef<AbortController | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!open) return;
    let alive = true;
    api
      .assistantInfo(projectId)
      .then((i) => alive && setInfo(i))
      .catch(() => alive && setInfo({ available: false, reason: "Could not reach the analysis server.", model: "", suggestions: [] }));
    const t = setTimeout(() => input.current?.focus(), 250);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [open, projectId]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(projectId), JSON.stringify(messages.slice(-60)));
    } catch {
      /* storage full or blocked: the chat still works for this session */
    }
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages, projectId]);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const patchLast = (fn: (m: Message) => Message) => setMessages((all) => [...all.slice(0, -1), fn(all[all.length - 1])]);

  const send = async (text: string) => {
    const q = text.trim();
    if (!q || busy) return;
    const history: ChatTurn[] = [...messages.filter((m) => !m.error && m.text), { role: "user", text: q } as Message].map((m) => ({ role: m.role, content: m.text }));
    setDraft("");
    setBusy(true);
    setMessages((all) => [...all, { id: `u${Date.now()}`, role: "user", text: q }, { id: `a${Date.now()}`, role: "assistant", text: "", pending: true }]);
    const ctrl = new AbortController();
    abort.current = ctrl;
    try {
      await api.chat(
        projectId,
        runId,
        history,
        (e) => {
          if (e.type === "text") patchLast((m) => ({ ...m, text: m.text + e.text }));
          else if (e.type === "tool") patchLast((m) => ({ ...m, tools: [...(m.tools ?? []), e.label] }));
          else if (e.type === "action") patchLast((m) => ({ ...m, actions: [...(m.actions ?? []), { params: e.params, reason: e.reason }] }));
          else if (e.type === "sources") patchLast((m) => ({ ...m, sources: e.sources }));
          else if (e.type === "error") patchLast((m) => ({ ...m, error: e.message }));
        },
        ctrl.signal,
      );
    } catch (err) {
      patchLast((m) => ({ ...m, error: err instanceof CanopyApiError ? err.message : "Something went wrong. Try again." }));
    } finally {
      patchLast((m) => ({ ...m, pending: false }));
      setBusy(false);
      abort.current = null;
    }
  };

  const stop = () => abort.current?.abort();
  const reset = () => {
    stop();
    setMessages([]);
    setDraft("");
    input.current?.focus();
  };

  const unavailable = info && !info.available;
  const empty = messages.length === 0;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px] md:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            role="dialog"
            aria-label="Canopy AI"
            className={cx(
              "fixed top-2 right-2 z-50 flex flex-col overflow-hidden rounded-2xl border border-separator-border bg-background-primary-default",
              "shadow-[0_24px_64px_-12px_rgba(0,0,0,0.35),0_8px_24px_-8px_rgba(0,0,0,0.2)]",
              dragging && "select-none",
            )}
            style={{
              width: desktop ? size.w : `calc(100vw - ${2 * GAP}px)`,
              height: desktop && size.h ? size.h : `calc(100dvh - ${2 * GAP}px)`,
              transformOrigin: "top right",
              transition: dragging ? "none" : "width 280ms cubic-bezier(0.22, 1, 0.36, 1), height 280ms cubic-bezier(0.22, 1, 0.36, 1)",
            }}
            initial={{ opacity: 0, x: 28, scale: 0.96, filter: "blur(6px)" }}
            animate={{ opacity: 1, x: 0, scale: 1, filter: "blur(0px)", transition: { type: "spring", stiffness: 420, damping: 36, mass: 0.7 } }}
            exit={{ opacity: 0, x: 20, scale: 0.97, filter: "blur(4px)", transition: { duration: 0.16, ease: [0.4, 0, 1, 1] } }}
          >
            {desktop && (
              <>
                {/* left edge: drag to change width */}
                <div
                  onPointerDown={start("w")}
                  onDoubleClick={() => setSize((s) => ({ ...s, w: NARROW }))}
                  title="Drag to resize · double-click to reset"
                  className="group absolute inset-y-0 left-0 z-10 w-2 cursor-ew-resize"
                >
                  <span
                    className={cx(
                      "absolute top-1/2 left-0.5 h-10 w-1 -translate-y-1/2 rounded-full transition-colors",
                      dragging === "w" ? "bg-brand" : "bg-transparent group-hover:bg-text-tertiary/50",
                    )}
                  />
                </div>
                {/* bottom edge: drag to change height */}
                <div
                  onPointerDown={start("h")}
                  onDoubleClick={() => setSize((s) => ({ ...s, h: null }))}
                  title="Drag to resize · double-click for full height"
                  className="group absolute inset-x-0 bottom-0 z-10 flex h-3 cursor-ns-resize items-end justify-center pb-1"
                >
                  <span className={cx("h-1 w-10 rounded-full transition-colors", dragging === "h" ? "bg-brand" : "bg-separator-border group-hover:bg-text-tertiary")} />
                </div>
              </>
            )}
            {/* header */}
            <div className="flex h-14 shrink-0 items-center gap-2 border-b border-separator-border px-4">
              <span className="flex size-6 items-center justify-center rounded-md bg-brand/15">
                <RiSparkling2Fill className="size-3.5 text-brand" aria-hidden />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-body-medium leading-tight text-text-primary">Canopy AI</p>
                <p className="truncate text-caption-1-regular leading-tight text-text-tertiary">{projectName}</p>
              </div>
              <button type="button" onClick={reset} aria-label="New conversation" className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-text-tertiary hover:bg-background-secondary-default hover:text-text-primary">
                <RiAddLine className="size-[18px]" />
              </button>
              <button type="button" onClick={() => setSize((s) => ({ ...s, w: wide ? NARROW : WIDE }))} aria-label={wide ? "Narrow panel" : "Widen panel"} className="hidden size-8 cursor-pointer items-center justify-center rounded-lg text-text-tertiary hover:bg-background-secondary-default hover:text-text-primary md:flex">
                {wide ? <RiContractLeftRightLine className="size-[18px]" /> : <RiExpandLeftRightLine className="size-[18px]" />}
              </button>
              <button type="button" onClick={onClose} aria-label="Close Canopy AI" className="flex size-8 cursor-pointer items-center justify-center rounded-lg text-text-tertiary hover:bg-background-secondary-default hover:text-text-primary">
                <RiCloseLine className="size-[18px]" />
              </button>
            </div>

            {/* body */}
            <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-width:thin]">
              {empty ? (
                <div className="relative flex min-h-full flex-col items-center justify-center gap-6 px-6 py-10">
                  {/* dot grid only behind the welcome, fading out before it reaches any edge */}
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0"
                    style={{
                      backgroundImage: "radial-gradient(var(--color-separator-border) 1px, transparent 1px)",
                      backgroundSize: "16px 16px",
                      maskImage: "radial-gradient(ellipse 70% 55% at 50% 38%, black 25%, transparent 75%)",
                      WebkitMaskImage: "radial-gradient(ellipse 70% 55% at 50% 38%, black 25%, transparent 75%)",
                    }}
                  />
                  <Orb />
                  <div className="relative text-center">
                    <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="text-[17px] font-medium tracking-[-0.01em] text-text-primary">
                      {greeting()}
                    </motion.p>
                    <motion.p initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.16 }} className="mt-1 text-body-2-regular text-text-tertiary">
                      Ask anything about this workspace, its boundary and its runs.
                    </motion.p>
                  </div>
                  {unavailable ? (
                    <div className="flex w-full max-w-[340px] items-start gap-3 rounded-xl border border-separator-border bg-background-primary-default p-3">
                      <RiKey2Line className="mt-0.5 size-4 shrink-0 text-confidence-medium" aria-hidden />
                      <p className="text-body-2-regular text-text-secondary">{info?.reason}</p>
                    </div>
                  ) : (
                    <ul className="relative flex w-full max-w-[340px] flex-col gap-2">
                      {(info?.suggestions ?? []).map((s, i) => (
                        <motion.li key={s} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 + i * 0.05 }}>
                          <button
                            type="button"
                            onClick={() => void send(s)}
                            className="flex w-full cursor-pointer items-center gap-3 rounded-xl border border-separator-border bg-background-primary-default px-3 py-2.5 text-left transition-colors hover:border-text-tertiary hover:bg-background-secondary-default"
                          >
                            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-background-secondary-default">
                              <RiSparkling2Fill className="size-3.5 text-text-tertiary" aria-hidden />
                            </span>
                            <span className="text-body-2-regular text-text-primary">{s}</span>
                          </button>
                        </motion.li>
                      ))}
                      {!info && Array.from({ length: 4 }, (_, i) => <li key={i} className="h-[50px] animate-pulse rounded-xl bg-background-secondary-default" />)}
                    </ul>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-5 px-4 py-5">
                  {messages.map((m, idx) =>
                    m.role === "user" ? (
                      <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-background-tertiary-default px-3.5 py-2 text-body-2-regular text-text-primary">
                        {m.text}
                      </motion.div>
                    ) : (
                      <motion.div key={m.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
                        <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brand/15">
                          <RiSparkling2Fill className={cx("size-3.5 text-brand", m.pending && "animate-pulse")} aria-hidden />
                        </span>
                        <div className="min-w-0 flex-1 text-body-2-regular text-text-secondary">
                          {m.tools?.map((t, ti) => (
                            <p key={ti} className="mb-2 flex items-center gap-1.5 text-caption-1-regular text-text-tertiary">
                              <RiSearchLine className="size-3.5" aria-hidden /> {t}
                            </p>
                          ))}
                          {m.text ? <Markdown text={m.text} /> : m.pending && !m.error ? <ThinkingDots /> : null}
                          {m.actions?.map((a, ai) => (
                            <ActionCard
                              key={ai}
                              action={a}
                              disabled={running || busy}
                              onApply={() => {
                                onApplyParams(a.params);
                                setMessages((all) => all.map((x, xi) => (xi === idx ? { ...x, actions: x.actions?.map((y, yi) => (yi === ai ? { ...y, applied: true } : y)) } : x)));
                              }}
                            />
                          ))}
                          {m.sources && m.sources.length > 0 && (
                            <ol className="mt-3 flex flex-col gap-1 border-t border-separator-border pt-2">
                              {m.sources.map((s) => (
                                <li key={s.n} className="flex min-w-0 gap-1.5 text-caption-1-regular">
                                  <span className="shrink-0 text-text-tertiary tabular-nums">[{s.n}]</span>
                                  <a href={s.url} target="_blank" rel="noreferrer noopener" className="truncate text-text-secondary underline decoration-separator-border underline-offset-2 hover:text-text-primary">
                                    {s.title}
                                  </a>
                                </li>
                              ))}
                            </ol>
                          )}
                          {m.error && <p className="mt-2 rounded-lg bg-background-tertiary-error px-3 py-2 text-body-2-regular text-text-primary">{m.error}</p>}
                        </div>
                      </motion.div>
                    ),
                  )}
                </div>
              )}
            </div>

            {/* composer: a soft fade so messages slide under it instead of being cut off */}
            <div className="relative shrink-0 bg-background-primary-default px-3 pt-2 pb-4">
              <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-6 h-6 bg-linear-to-t from-background-primary-default to-transparent" />
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void send(draft);
                }}
                className="relative rounded-2xl border border-separator-border bg-background-primary-default p-2 pt-3 shadow-xs transition-colors focus-within:border-text-tertiary"
              >
                {/* grip: drag up or down to change the message box height, double-click to reset */}
                <div
                  onPointerDown={box.start}
                  onDoubleClick={() => box.setH(BOX_DEFAULT)}
                  title="Drag to resize · double-click to reset"
                  className="group absolute inset-x-0 top-0 flex h-3 cursor-ns-resize justify-center pt-1"
                >
                  <span className={cx("h-1 w-8 rounded-full transition-colors", box.dragging ? "bg-brand" : "bg-separator-border group-hover:bg-text-tertiary")} />
                </div>
                <textarea
                  ref={input}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send(draft);
                    }
                  }}
                  style={{ height: box.h }}
                  disabled={!!unavailable}
                  placeholder={unavailable ? "Canopy AI is not set up on this server" : "Ask about crowns, runs, the boundary…"}
                  className="block w-full resize-none bg-transparent px-2 py-1.5 text-body-2-regular text-text-primary outline-none placeholder:text-text-tertiary"
                />
                <div className="flex items-center justify-end gap-2 px-1">
                  {busy ? (
                    <button type="button" onClick={stop} aria-label="Stop" className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-text-primary text-background-primary-default">
                      <RiStopFill className="size-3.5" />
                    </button>
                  ) : (
                    <button
                      type="submit"
                      aria-label="Send"
                      disabled={!draft.trim() || !!unavailable}
                      className="flex size-8 cursor-pointer items-center justify-center rounded-full bg-(--color-button-fill) text-(--color-button-fill-fg) shadow-xs ring-1 ring-black/10 transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <RiArrowUpLine className="size-4" />
                    </button>
                  )}
                </div>
              </form>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

function ThinkingDots() {
  return (
    <span className="inline-flex items-center gap-1.5 py-1 text-caption-1-regular text-text-tertiary">
      <RiLoader4Line className="size-3.5 animate-spin" aria-hidden /> Reading the workspace
    </span>
  );
}

/** The "Ask AI" trigger for the top bar. */
export function AskAiButton({ onClick, active }: { onClick: () => void; active: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        "group flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-[13px] font-medium ring-1 ring-inset transition-colors",
        active ? "bg-brand/15 text-text-primary ring-brand/40" : "text-text-primary ring-separator-border hover:bg-background-secondary-default",
      )}
    >
      <RiSparkling2Fill className="size-4 text-brand transition-transform duration-300 group-hover:rotate-12 group-hover:scale-110" aria-hidden />
      <span className="hidden sm:inline">Ask AI</span>
      <kbd className="ml-0.5 hidden rounded border border-separator-border px-1 font-mono text-[10px] text-text-tertiary lg:inline">Ctrl I</kbd>
    </button>
  );
}
