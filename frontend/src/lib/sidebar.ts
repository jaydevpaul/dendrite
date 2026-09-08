const STORAGE_KEY = "dendrite-sidebar";

/**
 * The conversation list starts open. It is the app's only navigator right now,
 * and a first-time user who cannot see it has no way to know it is there.
 */
export const DEFAULT_COLLAPSED = false;

/**
 * Read synchronously, in a `useState` initialiser rather than an effect, so
 * the first paint is already correct. Read in an effect instead and the
 * sidebar renders open and then snaps shut on every load.
 */
export function readSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "collapsed";
  } catch {
    // Private browsing, or storage disabled. Fall back rather than crash.
    return DEFAULT_COLLAPSED;
  }
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, collapsed ? "collapsed" : "open");
  } catch {
    // The preference simply will not persist. The app still works.
  }
}
