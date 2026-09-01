import { cn } from "@/lib/utils";
import type { NonSpanStrategy } from "./api";

/**
 * The composition strategy, shown as its real name in mono.
 *
 * Design doc section 4 reserves mono for token counts, model names, ids and
 * strategy labels. The name is not abbreviated: these five words are the
 * thesis, and a tool for measuring them should say which one is in force.
 */
export function StrategyTag({
  strategy,
  className,
}: {
  strategy: NonSpanStrategy;
  className?: string;
}) {
  return (
    <span
      className={cn("font-mono text-[11px] tracking-[-0.01em] text-dim", className)}
    >
      {strategy}
    </span>
  );
}
