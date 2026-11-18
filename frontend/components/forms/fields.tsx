"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const CONTROL =
  "mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted disabled:bg-ground disabled:text-muted";

export function Label({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: string;
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      <span className="text-sm font-medium text-ink">
        {label}
        {required && <span className="text-danger-ink"> *</span>}
      </span>
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-xs font-medium text-danger-ink">
          {error}
        </span>
      )}
    </label>
  );
}

export function TextInput({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...rest} />;
}

/**
 * An amount, typed as text.
 *
 * `inputMode="decimal"` gives a numeric keypad on a phone without making this a
 * `number` input: a number input would hand us a JavaScript float, and the whole
 * point is that the amount reaches the API as the string the user typed.
 */
export function MoneyInput({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="text"
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      placeholder="0.00"
      className={cn(CONTROL, "tnum text-right", className)}
      {...rest}
    />
  );
}

export function RateInput({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type="text"
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      placeholder="0.04250000"
      className={cn(CONTROL, "tnum text-right", className)}
      {...rest}
    />
  );
}

export function DateInput({
  className,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input type="date" className={cn(CONTROL, className)} {...rest} />;
}

export function Select({
  className,
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(CONTROL, className)} {...rest}>
      {children}
    </select>
  );
}

export function TextArea({
  className,
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, className)} rows={3} {...rest} />;
}

export function FormRow({ children, cols = 2 }: { children: ReactNode; cols?: 1 | 2 | 3 }) {
  const colClass = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3" }[cols];
  return <div className={cn("grid grid-cols-1 gap-4", colClass)}>{children}</div>;
}
