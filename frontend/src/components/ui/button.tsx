import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * shadcn/ui convention: the component lives in the repo as editable source
 * rather than arriving from a package, so the palette in index.css wins.
 *
 * Only `primary` is filled with the accent. The accent marks the current
 * branch and the primary action and nothing else -- a screen with two filled
 * accent buttons has no primary action. `danger` is outlined rather than
 * filled for the same reason.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-[13.5px] font-medium leading-none whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent font-semibold text-accent-ink hover:bg-accent-hover",
        secondary:
          "border border-line-strong bg-surface text-ink hover:bg-raised",
        ghost: "text-muted hover:bg-accent-tint hover:text-ink",
        danger:
          "border border-danger bg-transparent text-danger hover:bg-danger-tint",
      },
      size: {
        default: "h-9 px-[15px]",
        sm: "h-8 px-3 text-[12.5px]",
        lg: "h-11 px-[22px] text-[14.5px]",
        block: "h-10 w-full px-[15px]",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { buttonVariants };
