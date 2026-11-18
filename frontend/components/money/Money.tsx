import { cn } from "@/lib/cn";
import { formatMoney, formatRate, formatRatePct, isNegative } from "@/lib/money";

/**
 * An amount of money.
 *
 * The amount arrives as a string and leaves as a string: this component formats and
 * never calculates.  Figures are tabular and right-aligned so a column of balances
 * lines up digit for digit, and negatives are bracketed.
 */
export function Money({
  amount,
  currency,
  className,
  muteZero = false,
  colour = false,
}: {
  amount: string | null | undefined;
  currency?: string | null;
  className?: string;
  /** Render a zero balance in muted grey, so real movement stands out in a grid. */
  muteZero?: boolean;
  /** Colour a negative figure; off by default because brackets already say it. */
  colour?: boolean;
}) {
  const text = formatMoney(amount, currency ? { currency } : {});
  const zero = amount !== null && amount !== undefined && /^-?0+(\.0+)?$/.test(amount.trim());

  return (
    <span
      className={cn(
        "tnum tabular-nums",
        muteZero && zero && "text-muted",
        colour && isNegative(amount) && "text-danger-ink",
        className,
      )}
    >
      {text}
    </span>
  );
}

/** A profit or fee rate, shown as a percentage. */
export function RateBadge({
  rate,
  className,
  label,
}: {
  rate: string | null | undefined;
  className?: string;
  label?: string;
}) {
  if (!rate) return <span className="text-muted">—</span>;
  return (
    <span
      className={cn(
        "tnum inline-flex items-center rounded-md bg-ground px-2 py-0.5 text-xs font-medium text-ink ring-1 ring-border ring-inset",
        className,
      )}
      title={label}
    >
      {formatRatePct(rate)}
    </span>
  );
}

/** An FX rate, at the precision it was entered. */
export function FxRateValue({ rate }: { rate: string | null | undefined }) {
  return <span className="tnum tabular-nums">{formatRate(rate)}</span>;
}
