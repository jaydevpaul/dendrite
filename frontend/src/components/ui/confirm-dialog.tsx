import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";

/**
 * A centred confirm step for something irreversible.
 *
 * Native `<dialog>` rather than a hand-rolled overlay: it traps focus, closes
 * on Escape and paints its own backdrop, all of which would otherwise be code
 * to write and get wrong. Mounting this component *is* opening it - the caller
 * renders it conditionally - so there is no open/closed state kept in two
 * places.
 *
 * The backdrop blurs as well as darkens. The app's surfaces are close together
 * in value, so a dark scrim alone reads as "the lights went down" rather than
 * "this is in front of that"; the blur is what makes the layering obvious.
 */
export function ConfirmDialog({
  title,
  description,
  confirmLabel,
  pendingLabel,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  /** Shown on the confirm button while the request is in flight. */
  pendingLabel: string;
  pending?: boolean;
  error?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    // showModal(), not the `open` attribute: only the modal form gets the
    // backdrop, the focus trap and the top layer.
    ref.current?.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      // Escape fires `cancel`. Prevented, then routed through onCancel, so the
      // caller's state stays the one thing that decides whether this is open.
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
      // Clicks on the backdrop are dispatched to the dialog itself; anything
      // inside the card hits the card instead.
      onClick={(event) => {
        if (event.target === ref.current && !pending) onCancel();
      }}
      className="m-auto w-[min(25rem,calc(100vw-2rem))] rounded-xl border border-line-strong bg-surface p-0 text-ink backdrop:bg-scrim backdrop:backdrop-blur-[3px]"
    >
      <div className="p-5">
        <h2 className="text-[15px] leading-[1.35] font-semibold text-ink">{title}</h2>
        <div className="mt-2 text-[13px] leading-[1.55] text-muted">{description}</div>

        {error ? (
          <p className="mt-3 text-[12.5px] leading-[1.5] text-danger">{error}</p>
        ) : null}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending} autoFocus>
            Cancel
          </Button>
          <Button variant="danger" size="sm" onClick={onConfirm} disabled={pending}>
            {pending ? pendingLabel : confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
