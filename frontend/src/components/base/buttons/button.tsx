import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  ComponentType,
  ReactNode,
  Ref,
} from "react";
import { cx, sortCx } from "@/utils/cx";

/**
 * Figma source: Board UI → Buttons (node 3656:13819).
 *
 * Variant matrix from Figma:
 *   Type     = Primary | Secondary | Ghost | Danger
 *   Size     = Medium  | Small | Xs
 *   State    = Default | Hover | Active | Disabled        (CSS pseudo)
 *   OnlyIcon = false   | true
 *
 * Sizing (1:1 with Figma):
 *
 *                       Medium                    Small                     Xs
 *   container          h=36, p=8,   r=10         h=32, px=8 py=6, r=8      h=24, px=8, r=4
 *   gap                 2px                       2px                      1.33px→1
 *   icon                20×20                     18×18                    14×14
 *   label wrapper       px=4                      px=2                     px=2
 *   text style          Body 1/Medium             Body 1/Medium            Caption 1/Semibold
 *   icon-only square    36×36 (content-derived)   32×32 (forced size)      24×24 (forced size)
 *
 * `xs` is the smallest tier — first needed for the calendar template's
 * event-details modal ("Join" / edit-icon buttons, node 3920:10954), which
 * scales every dimension down by the same ~0.667 factor from Figma; the
 * table above rounds those to clean pixel values rather than reproducing
 * the fractional source numbers.
 *
 * Icons are rendered by the component itself via the `leadingIcon` /
 * `trailingIcon` props so the consumer can't pass the wrong size. Pass
 * a Remix Icon component reference (`RiAddLine`, not `<RiAddLine />`).
 *
 * For icon-only buttons:
 *   <Button iconOnly leadingIcon={RiAddLine} aria-label="Add" />
 *
 * The HTML `type` prop is preserved; Figma's "Type" enum is renamed to
 * `variant` to avoid the clash.
 */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "medium" | "small" | "xs";

type IconComponent = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean | "true" | "false";
}>;

export interface ButtonProps
  extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconOnly?: boolean;
  leadingIcon?: IconComponent;
  trailingIcon?: IconComponent;
  children?: ReactNode;
  ref?: Ref<HTMLButtonElement>;
}

export interface ButtonLinkProps
  extends Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "children"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconOnly?: boolean;
  leadingIcon?: IconComponent;
  trailingIcon?: IconComponent;
  children?: ReactNode;
  ref?: Ref<HTMLAnchorElement>;
}

const styles = sortCx({
  base: [
    "inline-flex items-center justify-center gap-0.5 whitespace-nowrap overflow-hidden",
    "font-sans select-none cursor-pointer",
    "button-press-motion",
    "font-medium outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-border-focus-ring",
    "disabled:cursor-not-allowed aria-disabled:cursor-not-allowed",
  ].join(" "),

  // Base shape per size (used when label is present OR medium icon-only).
  size: {
    // Kumo (Cloudflare) proportions: 36px base, rounded-lg, 12px side padding, 14px medium label.
    medium: "h-9 gap-1.5 rounded-lg px-3 text-[14px] leading-5 tracking-[-0.006em]",
    small:  "h-8 gap-1 rounded-lg px-2.5 text-[13px] leading-5 tracking-[-0.006em]",
    xs:     "h-6 gap-1 rounded-md px-2 text-[12px] leading-4",
  },

  // Icon-only override:
  //   Medium → keep p-2; w expands from content (8+20+8 = 36) → square.
  //   Small  → Figma forces 32×32 even though 8+18+8=34, so we hard-set size-8
  //            and zero the padding; the inner flex centers the 18px icon.
  //   Xs     → forces 24×24, content-centered — used for the calendar
  //            template's edit-icon buttons (timezone/participants/reminder).
  iconOnlySize: {
    medium: "size-9 p-0",      // hard 36×36, content-centered
    small:  "size-8 p-0",      // hard 32×32, content-centered
    xs:     "size-6 p-0",      // hard 24×24, content-centered
  },

  icon: {
    medium: "size-[18px] shrink-0",   // 18px
    small:  "size-4 shrink-0",        // 16px
    xs:     "size-3.5 shrink-0",      // 14px
  },

  label: {
    medium: "inline-flex items-center justify-center px-0.5 shrink-0",  // px=2
    small:  "inline-flex items-center justify-center px-0.5 shrink-0",  // px=2
    xs:     "inline-flex items-center justify-center px-0.5 shrink-0",  // px=2
  },

  // Kumo pattern: flat fills, a 1px ring instead of a border, shadow-xs; hover changes the fill only.
  variant: {
    primary: [
      "bg-(--color-button-fill) text-(--color-button-fill-fg) ring-1 ring-inset ring-black/10 shadow-xs",
      "hover:bg-(--color-button-fill-hover)",
      "disabled:opacity-50 disabled:shadow-none aria-disabled:opacity-50",
    ].join(" "),
    danger: [
      "bg-red-600 text-white ring-1 ring-inset ring-red-700 shadow-xs",
      "hover:bg-red-500",
      "disabled:opacity-50 disabled:shadow-none aria-disabled:opacity-50",
    ].join(" "),
    secondary: [
      "bg-background-primary-default text-text-primary ring-1 ring-inset ring-separator-border shadow-xs",
      "hover:bg-background-secondary-default active:bg-background-primary-active",
      "disabled:text-text-tertiary disabled:shadow-none disabled:hover:bg-background-primary-default",
      "aria-disabled:text-text-tertiary aria-disabled:shadow-none",
    ].join(" "),
    ghost: [
      "bg-transparent text-text-secondary hover:bg-background-secondary-default hover:text-text-primary",
      "disabled:text-text-tertiary disabled:hover:bg-transparent aria-disabled:text-text-tertiary",
    ].join(" "),
  },
});

export function Button({
  variant = "primary",
  size = "medium",
  iconOnly = false,
  leadingIcon: Leading,
  trailingIcon: Trailing,
  children,
  className,
  type = "button",
  ref,
  ...props
}: ButtonProps) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        styles.base,
        styles.size[size],
        styles.variant[variant],
        iconOnly && styles.iconOnlySize[size],
        className,
      )}
      {...props}
    >
      {Leading ? <Leading className={styles.icon[size]} aria-hidden /> : null}
      {!iconOnly && children !== undefined && children !== null && (
        <span className={styles.label[size]}>{children}</span>
      )}
      {!iconOnly && Trailing ? (
        <Trailing className={styles.icon[size]} aria-hidden />
      ) : null}
    </button>
  );
}

/** Anchor counterpart to Button for navigational actions. */
export function ButtonLink({
  variant = "primary",
  size = "medium",
  iconOnly = false,
  leadingIcon: Leading,
  trailingIcon: Trailing,
  children,
  className,
  ref,
  ...props
}: ButtonLinkProps) {
  return (
    <a
      ref={ref}
      className={cx(
        styles.base,
        styles.size[size],
        styles.variant[variant],
        iconOnly && styles.iconOnlySize[size],
        className,
      )}
      {...props}
    >
      {Leading ? <Leading className={styles.icon[size]} aria-hidden /> : null}
      {!iconOnly && children !== undefined && children !== null && (
        <span className={styles.label[size]}>{children}</span>
      )}
      {!iconOnly && Trailing ? (
        <Trailing className={styles.icon[size]} aria-hidden />
      ) : null}
    </a>
  );
}

/** Style maps, exported for advanced composition and the dev Design Tuner. */
export const buttonStyles = styles;
