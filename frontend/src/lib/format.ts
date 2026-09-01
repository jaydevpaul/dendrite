/**
 * Date formatting via `Intl`, so no date library enters the dependency budget
 * (design doc section 2: every runtime package is justified in that file).
 */

const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

const absolute = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

/**
 * "3 minutes ago", "yesterday", "2 months ago".
 *
 * Backend timestamps are `TIMESTAMP(timezone=True)`, so they arrive with an
 * offset and parse unambiguously. Anything under 45 seconds either way reads
 * as "just now": the server clock and the browser clock are not the same
 * clock, and a freshly created row must never render as "in 2 seconds".
 */
export function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";

  const seconds = (then - Date.now()) / 1000;
  const magnitude = Math.abs(seconds);

  if (magnitude < 45) return "just now";
  if (magnitude < HOUR) return relative.format(Math.round(seconds / MINUTE), "minute");
  if (magnitude < DAY) return relative.format(Math.round(seconds / HOUR), "hour");
  if (magnitude < WEEK) return relative.format(Math.round(seconds / DAY), "day");
  if (magnitude < MONTH) return relative.format(Math.round(seconds / WEEK), "week");
  if (magnitude < YEAR) return relative.format(Math.round(seconds / MONTH), "month");
  return relative.format(Math.round(seconds / YEAR), "year");
}

/** The exact timestamp, for a `title` attribute behind the relative one. */
export function formatAbsoluteTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : absolute.format(date);
}
