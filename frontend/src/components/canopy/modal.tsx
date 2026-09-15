import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { RiCloseLine } from "@remixicon/react";
import { cx } from "@/utils/cx";

/**
 * Dialog shell lifted from BoardUI's SettingsModal: black/70 backdrop, the same
 * fade + blur + scale transition, rounded-3xl panel on background/full, and the
 * title row with the round close button. Only the nav rail is left out.
 */
export function Modal({
  isOpen,
  onClose,
  title,
  children,
  className,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);
  const unmountTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen) {
      if (unmountTimer.current) clearTimeout(unmountTimer.current);
      setMounted(true);
      requestAnimationFrame(() => requestAnimationFrame(() => setVisible(true)));
    } else {
      setVisible(false);
      unmountTimer.current = setTimeout(() => setMounted(false), 320);
    }
    return () => {
      if (unmountTimer.current) clearTimeout(unmountTimer.current);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen, onClose]);

  if (!mounted || typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-100 flex items-center justify-center p-4" role="presentation">
      <button
        type="button"
        aria-label={`Close ${title}`}
        tabIndex={-1}
        onClick={onClose}
        className={cx(
          "absolute inset-0 cursor-default bg-black/70 transition-opacity duration-300 ease-out",
          visible ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        className={cx(
          "relative",
          "transform-gpu transition-[opacity,transform,filter] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] will-change-[opacity,transform,filter]",
          visible ? "scale-100 opacity-100 blur-0" : "scale-[0.85] opacity-0 blur-[4px]",
        )}
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={title}
          tabIndex={-1}
          className={cx(
            "relative flex max-h-[calc(100dvh-32px)] w-[560px] max-w-[calc(100vw-32px)] flex-col",
            "overflow-clip rounded-3xl bg-background-full shadow-xs outline-none",
            className,
          )}
        >
          <div className="flex shrink-0 items-center justify-between px-8 pt-8 pb-3">
            <h2 className="text-title-3-medium text-text-primary">{title}</h2>
            <button
              type="button"
              aria-label={`Close ${title}`}
              onClick={onClose}
              className={cx(
                "flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-full",
                "bg-background-tertiary-default text-foreground-icon-secondary",
                "transition-colors duration-150 ease hover:bg-background-tertiary-hover",
                "outline-none focus-visible:ring-2 focus-visible:ring-border-focus-ring",
              )}
            >
              <RiCloseLine className="size-4" aria-hidden />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-8 pb-8">{children}</div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
