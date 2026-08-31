import { cn } from "@/lib/utils";

/**
 * The Dendrite mark: a leaf whose veins branch.
 *
 * Filled silhouette, not strokes — that is what makes it read at 16px and gives
 * it the soft, emoji-like weight the earlier stroke-and-dots mark lacked. The
 * venation is the product: a midrib that carries straight on (continuation) with
 * side veins leaving it at an angle (branches).
 *
 * Veins are drawn in translucent black rather than a fixed colour, so they read
 * correctly whatever the leaf itself is filled with — they only ever need
 * contrast against the leaf, never against the page behind it.
 */
export function DendriteMark({
  className,
  tone = "accent",
}: {
  className?: string;
  /**
   * `accent` for the brand lockup, `current` to inherit surrounding text
   * colour, `panel` for the fixed-dark brand panel — where the light theme's
   * accent would be a dark green on a dark ground.
   */
  tone?: "accent" | "current" | "panel";
}) {
  const fill =
    tone === "current"
      ? "currentColor"
      : tone === "panel"
        ? "var(--color-panel-accent)"
        : "var(--color-accent)";

  return (
    <svg
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      className={cn("size-6", className)}
    >
      {/* stem */}
      <path
        d="M15 53C12.5 56 10.5 58 9 60.5"
        stroke={fill}
        strokeWidth="4.5"
        strokeLinecap="round"
      />
      {/* leaf body */}
      <path
        d="M14 54C12 32 22 14 48 12C50 38 38 52 14 54Z"
        fill={fill}
      />
      {/* venation: midrib plus four side veins */}
      <g
        stroke="rgb(0 0 0 / 0.34)"
        strokeWidth="3"
        strokeLinecap="round"
        fill="none"
      >
        <path d="M15 53L45 15" />
        <path d="M24 42L19 33" />
        <path d="M24 42L30.5 45" />
        <path d="M32 32L28 24" />
        <path d="M32 32L38.5 34.5" />
      </g>
    </svg>
  );
}

/** Mark in a rounded tile plus wordmark — the standard lockup. */
export function Logo({
  className,
  size = "md",
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const tile = {
    sm: "size-7 rounded-[7px]",
    md: "size-9 rounded-[9px]",
    lg: "size-11 rounded-[11px]",
  }[size];
  const mark = { sm: "size-[18px]", md: "size-[23px]", lg: "size-7" }[size];
  const word = {
    sm: "text-[14px]",
    md: "text-[16.5px]",
    lg: "text-[19px]",
  }[size];

  return (
    <span className={cn("inline-flex items-center gap-[10px]", className)}>
      <span
        className={cn(
          "grid shrink-0 place-items-center border border-line bg-raised",
          tile,
        )}
      >
        <DendriteMark className={mark} />
      </span>
      <span className={cn("font-semibold tracking-[-0.017em]", word)}>
        Dendrite
      </span>
    </span>
  );
}
