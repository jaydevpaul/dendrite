export type Theme = "dark" | "light";

const STORAGE_KEY = "dendrite-theme";

/**
 * Dark is the default: this is a tool that gets looked at for long stretches,
 * often at night. The OS preference is deliberately NOT consulted -- a stated
 * product default beats a guess, and the toggle is one click away.
 */
export const DEFAULT_THEME: Theme = "dark";

export function readTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === "light" ? "light" : DEFAULT_THEME;
  } catch {
    // Private browsing, or storage disabled. Fall back rather than crash.
    return DEFAULT_THEME;
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Preference simply will not persist. The app still works.
  }
}
