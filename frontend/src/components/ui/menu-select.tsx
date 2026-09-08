import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * A one-of-many picker whose list is part of the page.
 *
 * This exists because a native `select` cannot be themed. Its dropdown is
 * drawn by the operating system, not the document: setting `background-color`
 * and `color` on `option` is honoured by some browsers, ignored by Chrome on
 * Windows, and the highlight on the row under the cursor is never reachable at
 * all. The result was a white card with a system-blue bar in the middle of a
 * dark app. **Do not replace this with a `select` again** -- the colours are
 * not a matter of getting the CSS right, they are outside the page.
 *
 * Still no dependency. Radix earns its place on a listbox that needs
 * multi-select, typeahead, or a portal escaping an overflow container; this
 * one picks one of four short strings, so it is a button, a list, and the
 * keyboard handling that makes them a listbox.
 *
 * Focus stays on the button while the list is open, with the active row
 * tracked by `aria-activedescendant`. That is the pattern for a listbox whose
 * options are not themselves focusable, and it means nothing has to hand focus
 * back on close.
 *
 * The list opens **upward by default**, because the first place this was used
 * is the prompt box at the bottom of the viewport, where a list opening
 * downward is off the bottom of the screen. The branch composer sits in the
 * middle of the thread and wants the other direction: upward there covers the
 * reply above it, which is the text the branch is being taken from.
 *
 * Set in the interface sans, not the mono, even when the values are
 * identifiers. Mono marks a value being *reported* -- a token count, a model
 * id, the arm a stored reply ran under. This is a value being *chosen*, and a
 * control typeset as data reads as something to look at rather than something
 * to operate.
 */
export function MenuSelect<T extends string>({
  value,
  options,
  onChange,
  label,
  disabled,
  className,
  title,
  direction = "up",
}: {
  value: T;
  options: readonly T[];
  onChange: (value: T) => void;
  /** Accessible name. There is no visible label in the prompt box. */
  label: string;
  disabled?: boolean;
  className?: string;
  title?: string;
  /** Which way the list opens. See the note above on why "up" is the default. */
  direction?: "up" | "down";
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => Math.max(options.indexOf(value), 0));
  const wrapper = useRef<HTMLDivElement>(null);
  const listId = `${label.replace(/\s+/g, "-").toLowerCase()}-list`;

  // Reopening should start from what is currently selected, not from wherever
  // the arrow keys were left last time.
  useEffect(() => {
    if (open) setActive(Math.max(options.indexOf(value), 0));
  }, [open, options, value]);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: PointerEvent) {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false);
    }
    // `pointerdown`, not `click`: closing on click would fire after a mousedown
    // has already moved focus, so the button would appear to reopen.
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function choose(index: number) {
    const next = options[index];
    if (next !== undefined && next !== value) onChange(next);
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }

    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === " ") {
        event.preventDefault();
        setOpen(true);
      }
      return;
    }

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((current) => (current + 1) % options.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((current) => (current - 1 + options.length) % options.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      setActive(0);
    } else if (event.key === "End") {
      event.preventDefault();
      setActive(options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      choose(active);
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={wrapper} className="relative">
      <button
        type="button"
        aria-label={label}
        title={title}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={onKeyDown}
        className={cn(
          "inline-flex h-8 max-w-full items-center gap-[6px] rounded-md border border-transparent px-2 text-[12.5px] text-dim transition-colors",
          "hover:bg-raised hover:text-ink",
          "focus-visible:border-accent focus-visible:outline-none",
          open && "bg-raised text-ink",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
      >
        <span className="truncate">{value}</span>
        <ChevronDown
          aria-hidden
          className={cn(
            "size-[13px] shrink-0 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open ? (
        // A popup is the one place elevation is doing real work rather than
        // decorating -- it has to read as floating over the thread, not as
        // part of it. Hence a shadow here and nowhere else.
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className={cn(
            "absolute left-0 z-20 min-w-full rounded-lg border border-line-strong bg-surface p-1 shadow-[0_10px_30px_rgb(0_0_0/0.38)]",
            direction === "up" ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {options.map((option, index) => {
            const selected = option === value;
            return (
              <li
                key={option}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={selected}
                onPointerEnter={() => setActive(index)}
                onClick={() => choose(index)}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-[5px] px-2 py-[6px] text-[12.5px] whitespace-nowrap",
                  index === active ? "bg-accent-tint text-ink" : "text-muted",
                )}
              >
                <Check
                  aria-hidden
                  className={cn(
                    "size-[13px] shrink-0",
                    selected ? "text-accent" : "invisible",
                  )}
                />
                {option}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
