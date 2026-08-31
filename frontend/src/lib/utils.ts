import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge conditional class names, with later Tailwind utilities winning over
 * earlier conflicting ones. This is the shadcn/ui convention: `clsx` handles
 * the conditionals, `tailwind-merge` resolves `px-2 px-4` down to `px-4`
 * instead of leaving both in the class string.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
