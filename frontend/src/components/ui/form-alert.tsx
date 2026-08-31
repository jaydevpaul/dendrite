import { cn } from "@/lib/utils";

/**
 * Form-level failure (a 409 from signup, a 401 from login) as opposed to a
 * field-level one. A left rule plus a tint rather than a boxed card: section 4
 * of the design doc asks for spacing and background shifts over borders
 * everywhere.
 */
export function FormAlert({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      role="alert"
      className={cn(
        "rounded-r border-l-2 border-danger bg-danger-tint px-3 py-[9px] text-[13px] text-ink",
        className,
      )}
    >
      {children}
    </p>
  );
}
