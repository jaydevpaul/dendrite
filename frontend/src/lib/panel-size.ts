/**
 * How wide the reader has dragged each side panel.
 *
 * Per browser rather than per user, unlike whether the navigator is open: a
 * width is a fact about the window it was dragged in, and carrying 420px from
 * a wide monitor onto a laptop would be restoring a preference nobody has.
 */
const STORAGE_PREFIX = "dendrite-panel-width";

export interface PanelBounds {
  default: number;
  min: number;
  max: number;
}

/** The conversation list. Wide enough for a title, no wider by default. */
export const SIDEBAR_BOUNDS: PanelBounds = { default: 264, min: 200, max: 460 };

/** The navigator. The graph is the widest thing in the app, so it goes wider. */
export const NAVIGATOR_BOUNDS: PanelBounds = { default: 320, min: 240, max: 620 };

/** What the thread itself must keep, whatever the panels are dragged to. */
const THREAD_FLOOR = 420;

/**
 * Clamped against the window as well as the bounds, so a panel dragged wide on
 * a big monitor does not squeeze the thread to nothing on a small one. The
 * thread is the job; the panels are beside it.
 */
export function clampPanelWidth(width: number, bounds: PanelBounds, viewport: number): number {
  const room = Math.max(viewport - THREAD_FLOOR, bounds.min);
  const max = Math.min(bounds.max, room);
  if (!Number.isFinite(width)) return Math.min(bounds.default, max);
  return Math.min(Math.max(Math.round(width), bounds.min), max);
}

export function readPanelWidth(key: string, bounds: PanelBounds, viewport: number): number {
  try {
    const stored = localStorage.getItem(`${STORAGE_PREFIX}:${key}`);
    if (stored === null) return clampPanelWidth(bounds.default, bounds, viewport);
    return clampPanelWidth(Number(stored), bounds, viewport);
  } catch {
    // Private browsing, or storage disabled.
    return clampPanelWidth(bounds.default, bounds, viewport);
  }
}

export function writePanelWidth(key: string, width: number): void {
  try {
    localStorage.setItem(`${STORAGE_PREFIX}:${key}`, String(Math.round(width)));
  } catch {
    // The width will not persist. Dragging still works this session.
  }
}
