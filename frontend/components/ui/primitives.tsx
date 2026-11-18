import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/cn";

/** A surface card: the unit every screen is built from. */
export function Card({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={cn("rounded-card border border-border bg-surface shadow-xs", className)}
    >
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn("px-5 py-4", bodyClassName)}>{children}</div>
    </section>
  );
}

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

const BUTTON_CLASS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-ink hover:bg-accent-hover disabled:bg-accent/50",
  secondary: "bg-surface text-ink ring-1 ring-border ring-inset hover:bg-ground",
  danger: "bg-danger-ink text-white hover:bg-danger-ink/90",
  ghost: "text-accent hover:bg-success-tint",
};

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60";

export function Button({
  variant = "primary",
  className,
  ...rest
}: ComponentProps<"button"> & { variant?: ButtonVariant }) {
  return <button className={cn(BUTTON_BASE, BUTTON_CLASS[variant], className)} {...rest} />;
}

export function ButtonLink({
  variant = "secondary",
  className,
  ...rest
}: ComponentProps<typeof Link> & { variant?: ButtonVariant }) {
  return <Link className={cn("btn", BUTTON_BASE, BUTTON_CLASS[variant], className)} {...rest} />;
}

/** A labelled figure: the unit a KPI row is built from. */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "default" | "warning" | "danger" | "success";
}) {
  const toneClass = {
    default: "text-ink",
    warning: "text-warning-ink",
    danger: "text-danger-ink",
    success: "text-success-ink",
  }[tone];
  return (
    <div className="rounded-card border border-border bg-surface px-5 py-4">
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p className={cn("tnum mt-1 text-2xl font-semibold", toneClass)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-prose text-sm text-muted">{description}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

/** The API's own message, shown verbatim: it is written for the person reading it. */
export function ErrorBanner({
  title = "That did not go through",
  message,
  details,
}: {
  title?: string;
  message: string;
  details?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-danger-ink/20 bg-danger-tint px-4 py-3 text-sm text-danger-ink"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-0.5">{message}</p>
      {details && <div className="mt-2 text-xs">{details}</div>}
    </div>
  );
}

export function Banner({
  tone,
  title,
  children,
}: {
  tone: "warning" | "success" | "danger" | "info";
  title: string;
  children?: ReactNode;
}) {
  const toneClass = {
    warning: "border-warning-ink/20 bg-warning-tint text-warning-ink",
    success: "border-success-ink/20 bg-success-tint text-success-ink",
    danger: "border-danger-ink/20 bg-danger-tint text-danger-ink",
    info: "border-border bg-ground text-ink",
  }[tone];
  return (
    <div className={cn("rounded-lg border px-4 py-3 text-sm", toneClass)}>
      <p className="font-semibold">{title}</p>
      {children && <div className="mt-0.5">{children}</div>}
    </div>
  );
}

/** A label/value pair, as used on every detail card. */
export function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <dt className="text-xs font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

export function FieldList({ children, cols = 2 }: { children: ReactNode; cols?: 1 | 2 | 3 | 4 }) {
  const colClass = {
    1: "sm:grid-cols-1",
    2: "sm:grid-cols-2",
    3: "sm:grid-cols-2 lg:grid-cols-3",
    4: "sm:grid-cols-2 lg:grid-cols-4",
  }[cols];
  return <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-4", colClass)}>{children}</dl>;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-prose text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
