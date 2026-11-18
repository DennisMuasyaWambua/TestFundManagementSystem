/**
 * Money formatting -- and nothing else.
 *
 * The frontend never does money arithmetic (principle 1).  Amounts arrive from the
 * API as strings, are formatted here for display, and are sent back as strings.
 * There is deliberately no `parseFloat` in this file and no `number` in any exported
 * signature that carries an amount: a float would silently lose cents on a
 * 24-digit balance, and that is the one bug this system must never have.
 */

const GROUPER = /\B(?=(\d{3})+(?!\d))/g;

export type Money = string;

type Parsed = { negative: boolean; whole: string; fraction: string };

function parse(amount: Money): Parsed | null {
  const trimmed = amount.trim();
  if (!/^-?\d+(\.\d+)?$/.test(trimmed)) return null;
  const negative = trimmed.startsWith("-");
  const unsigned = negative ? trimmed.slice(1) : trimmed;
  const [whole = "0", fraction = ""] = unsigned.split(".");
  return { negative, whole, fraction };
}

/** Pad or truncate the fraction to exactly two places, by string surgery only. */
function toCents(fraction: string): string {
  return (fraction + "00").slice(0, 2);
}

/**
 * `1234567.5` -> `1,234,567.50`; `-10.5` -> `(10.50)`.
 *
 * Negatives are shown in brackets, which is what the finance team reads, and is
 * unambiguous on a printed statement where a minus sign can be lost.
 */
export function formatMoney(
  amount: Money | null | undefined,
  options: { brackets?: boolean; currency?: string | null } = {},
): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const parsed = parse(amount);
  if (parsed === null) return amount;

  const { brackets = true } = options;
  const grouped = parsed.whole.replace(GROUPER, ",");
  const body = `${grouped}.${toCents(parsed.fraction)}`;
  const withCurrency = options.currency ? `${options.currency} ${body}` : body;

  if (!parsed.negative) return withCurrency;
  return brackets ? `(${withCurrency})` : `-${withCurrency}`;
}

/** True when the amount is negative -- used only to pick a colour, never to compute. */
export function isNegative(amount: Money | null | undefined): boolean {
  if (!amount) return false;
  const parsed = parse(amount);
  return parsed !== null && parsed.negative && /[1-9]/.test(parsed.whole + parsed.fraction);
}

/** True when the amount is exactly zero, whatever its scale (`0`, `0.00`, `-0.00`). */
export function isZero(amount: Money | null | undefined): boolean {
  if (amount === null || amount === undefined || amount === "") return false;
  const parsed = parse(amount);
  return parsed !== null && !/[1-9]/.test(parsed.whole + parsed.fraction);
}

/**
 * A rate as a percentage: `0.0425` -> `4.25%`.
 *
 * Rates carry eight decimal places, so the shift is done on the string to avoid
 * float drift (0.0425 * 100 is 4.250000000000001 in IEEE 754).
 */
export function formatRatePct(rate: string | null | undefined, places = 2): string {
  if (!rate) return "—";
  const parsed = parse(rate);
  if (parsed === null) return rate;

  const digits = parsed.whole + parsed.fraction;
  const pointFromRight = parsed.fraction.length - 2;
  let shifted: string;
  if (pointFromRight <= 0) {
    shifted = digits + "0".repeat(-pointFromRight);
  } else {
    const cut = digits.length - pointFromRight;
    shifted = `${digits.slice(0, cut) || "0"}.${digits.slice(cut)}`;
  }
  const [whole = "0", fraction = ""] = shifted.replace(/^0+(?=\d)/, "").split(".");
  const rounded = places === 0 ? whole : `${whole}.${(fraction + "0".repeat(places)).slice(0, places)}`;
  return `${parsed.negative ? "-" : ""}${rounded}%`;
}

/** An FX rate, shown at full precision with trailing zeros trimmed. */
export function formatRate(rate: string | null | undefined): string {
  if (!rate) return "—";
  const parsed = parse(rate);
  if (parsed === null) return rate;
  const fraction = parsed.fraction.replace(/0+$/, "");
  const body = fraction ? `${parsed.whole}.${fraction}` : parsed.whole;
  return `${parsed.negative ? "-" : ""}${body}`;
}
