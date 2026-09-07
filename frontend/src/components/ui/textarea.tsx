import { forwardRef, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * Same edge treatment as `Input`, and for the same reason: the border is drawn
 * with `line-strong`, never `line`. A divider may sit at 1.26:1 because it is
 * decoration; the edge of a field is the only thing telling you where to type.
 *
 * `forwardRef` so the composer can focus it on mount, refocus it after a send,
 * and measure it to grow with the text.
 */
export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(
        "w-full resize-none rounded-lg border border-line-strong bg-surface px-[13px] py-[10px] text-sm leading-[1.55] text-ink transition-[border-color,box-shadow]",
        "placeholder:text-dim",
        "focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--color-accent-tint)] focus-visible:outline-none",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});
