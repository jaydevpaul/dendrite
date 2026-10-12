import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import {
  clampPanelWidth,
  readPanelWidth,
  writePanelWidth,
  type PanelBounds,
} from "@/lib/panel-size";

/**
 * A panel the reader can drag wider, and the divider they drag it by.
 *
 * The width lives here rather than in the panel's own component because the
 * shell is what owns layout - the panel renders inside whatever width it is
 * given, exactly as it did when the width was a constant.
 *
 * `setPointerCapture` rather than window listeners: the pointer leaves the
 * 5px divider on the first frame of any real drag, and capture is what keeps
 * the events coming to the element that started it. It also ends the drag
 * correctly when the pointer is released outside the window.
 *
 * **Text selection is suppressed for the duration of the drag**, and that is
 * not only cosmetic here: a drag across the thread would otherwise select the
 * reply underneath and pop up the branch offer, so resizing a panel would
 * appear to be trying to branch.
 */
export function useResizablePanel(storageKey: string, bounds: PanelBounds) {
  const [width, setWidth] = useState(() =>
    readPanelWidth(storageKey, bounds, window.innerWidth),
  );

  // Re-clamped when the window changes, so a width dragged on a wide monitor
  // does not leave the thread with nothing on a narrow one.
  useEffect(() => {
    function onResize() {
      setWidth((current) => clampPanelWidth(current, bounds, window.innerWidth));
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [bounds]);

  const set = useCallback(
    (next: number) => {
      const clamped = clampPanelWidth(next, bounds, window.innerWidth);
      setWidth(clamped);
      return clamped;
    },
    [bounds],
  );

  const commit = useCallback(
    (next: number) => writePanelWidth(storageKey, set(next)),
    [set, storageKey],
  );

  return { width, set, commit, bounds };
}

/** How far one arrow-key press moves the divider. */
const STEP = 16;

export function ResizeHandle({
  /** Which side of the divider the panel is on. */
  side,
  width,
  bounds,
  onDrag,
  onCommit,
  label,
}: {
  side: "left" | "right";
  width: number;
  bounds: PanelBounds;
  /** Called continuously while dragging. */
  onDrag: (width: number) => void;
  /** Called once when the drag ends, and by the keyboard on each press. */
  onCommit: (width: number) => void;
  label: string;
}) {
  const [dragging, setDragging] = useState(false);
  const start = useRef({ x: 0, width: 0 });
  const latest = useRef(width);
  latest.current = width;

  useEffect(() => {
    if (!dragging) return;
    const body = document.body;
    const previousSelect = body.style.userSelect;
    const previousCursor = body.style.cursor;
    body.style.userSelect = "none";
    body.style.cursor = "col-resize";
    return () => {
      body.style.userSelect = previousSelect;
      body.style.cursor = previousCursor;
    };
  }, [dragging]);

  return (
    <div
      // A resize divider is a separator with a value, which is what lets the
      // arrow keys be a real alternative to dragging rather than a courtesy.
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={bounds.min}
      aria-valuemax={bounds.max}
      tabIndex={0}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = { x: event.clientX, width };
        setDragging(true);
      }}
      onPointerMove={(event) => {
        if (!dragging) return;
        const delta = event.clientX - start.current.x;
        // Dragging right widens a left-hand panel and narrows a right-hand
        // one. Same gesture, opposite sign.
        onDrag(start.current.width + (side === "left" ? delta : -delta));
      }}
      onPointerUp={(event) => {
        if (!dragging) return;
        event.currentTarget.releasePointerCapture(event.pointerId);
        setDragging(false);
        onCommit(latest.current);
      }}
      onPointerCancel={() => {
        if (!dragging) return;
        setDragging(false);
        onCommit(latest.current);
      }}
      onDoubleClick={() => onCommit(bounds.default)}
      onKeyDown={(event) => {
        const towards = side === "left" ? 1 : -1;
        if (event.key === "ArrowRight") onCommit(width + STEP * towards);
        else if (event.key === "ArrowLeft") onCommit(width - STEP * towards);
        else if (event.key === "Home") onCommit(bounds.default);
        else return;
        event.preventDefault();
      }}
      title={`${label} — drag, or double-click to reset`}
      className={cn(
        // Sits over the border it replaces, wider than it looks so it can
        // actually be grabbed: 1px of visible line, 9px of target.
        "absolute inset-y-0 z-20 hidden w-[9px] cursor-col-resize lg:block",
        side === "left" ? "-right-[5px]" : "-left-[5px]",
        "after:absolute after:inset-y-0 after:left-1/2 after:w-[1px] after:-translate-x-1/2",
        "after:transition-colors after:content-['']",
        dragging ? "after:bg-accent" : "after:bg-transparent hover:after:bg-line-strong",
        "focus-visible:after:bg-accent focus-visible:outline-none",
      )}
    />
  );
}
