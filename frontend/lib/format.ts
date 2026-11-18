/** Dates, labels and other display-only helpers. */

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * `2026-01-31` -> `31 Jan 2026`.
 *
 * Parsed by hand rather than with `new Date(...)`: the Date constructor reads a bare
 * ISO date as midnight UTC, which renders as the previous day for anyone west of
 * Greenwich.  A value date must never shift.
 */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  const index = Number(month) - 1;
  return `${Number(day)} ${MONTHS[index] ?? month} ${year}`;
}

/** `2026-01-31T09:15:22` -> `31 Jan 2026 09:15`. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const time = /T(\d{2}):(\d{2})/.exec(value);
  const date = formatDate(value);
  return time ? `${date} ${time[1]}:${time[2]}` : date;
}

/** `PENDING_APPROVAL` -> `Pending approval`. */
export function humanise(value: string | null | undefined): string {
  if (!value) return "—";
  const spaced = value.replace(/_/g, " ").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Today in the ISO form the API expects, in the user's own timezone. */
export function todayIso(): string {
  const now = new Date();
  const month = `${now.getMonth() + 1}`.padStart(2, "0");
  const day = `${now.getDate()}`.padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** The last day of the month before the given ISO date -- the usual period end. */
export function previousMonthEnd(iso: string = todayIso()): string {
  const match = /^(\d{4})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const end = new Date(Date.UTC(year, month - 1, 0));
  const m = `${end.getUTCMonth() + 1}`.padStart(2, "0");
  const d = `${end.getUTCDate()}`.padStart(2, "0");
  return `${end.getUTCFullYear()}-${m}-${d}`;
}

export function pluralise(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
