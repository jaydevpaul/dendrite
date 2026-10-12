const STORAGE_PREFIX = "dendrite-navigator";

/**
 * The navigator panel starts closed.
 *
 * It answers "what else is in this conversation", which is a question the
 * reader has to have before the answer is worth the width. The thread is the
 * job; a panel open by default would take a third of the screen away from it
 * on first visit, before there is a single branch to look at.
 */
export const DEFAULT_OPEN = false;

/**
 * Per user, because "remember it open" is a habit rather than a device
 * setting, and two people sharing a browser should not inherit each other's.
 *
 * It is still local storage, not a stored preference: there is no preferences
 * endpoint and inventing one for a boolean is not worth a column. So this is
 * per user *per browser*, and a second machine starts closed again.
 */
function keyFor(userId: string | undefined): string {
  return userId === undefined ? STORAGE_PREFIX : `${STORAGE_PREFIX}:${userId}`;
}

/**
 * Read synchronously in a `useState` initialiser, never in an effect: read in
 * an effect and the panel renders closed and then jumps open on every load.
 */
export function readNavigatorOpen(userId: string | undefined): boolean {
  try {
    return localStorage.getItem(keyFor(userId)) === "open";
  } catch {
    // Private browsing, or storage disabled. Fall back rather than crash.
    return DEFAULT_OPEN;
  }
}

export function writeNavigatorOpen(userId: string | undefined, open: boolean): void {
  try {
    localStorage.setItem(keyFor(userId), open ? "open" : "closed");
  } catch {
    // The preference will not persist. The panel still works this session.
  }
}
