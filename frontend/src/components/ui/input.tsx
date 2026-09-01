import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * The border uses `line-strong`, not `line`. `line` measures 1.26:1 against the
 * page in light mode -- correct for a divider, and not enough for the edge of a
 * field, where the border is the only thing telling you where to click.
 *
 * `forwardRef` (shadcn's own convention) so callers can focus the field
 * imperatively. The conversation composer needs that: it mounts on a click and
 * must take focus, and `autoFocus` is the wrong tool -- it fires once on mount
 * and cannot re-focus after a failed submit.
 */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "h-9 w-full rounded-md border border-line-strong bg-surface px-[11px] text-sm text-ink transition-[border-color,box-shadow]",
          "placeholder:text-dim",
          "focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--color-accent-tint)] focus-visible:outline-none",
          "aria-[invalid=true]:border-danger",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      />
    );
  },
);
