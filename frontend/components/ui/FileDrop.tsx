"use client";

import { useRef, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * A file picker that shows the SHA-256 of what was chosen.
 *
 * The hash is computed in the browser and displayed before anything is uploaded, so
 * the person uploading a wet-signed letter or a custodian statement can compare it
 * with the hash the system records -- and see for themselves that the file stored is
 * the file they picked.  The backend computes its own hash; this one is for the eye.
 */
export function FileDrop({
  name,
  label,
  accept,
  hint,
  required = false,
  existing,
  onFileChange,
}: {
  name: string;
  label: string;
  accept?: string;
  hint?: string;
  required?: boolean;
  /** Already on the batch from an earlier upload -- shown when resuming a batch. */
  existing?: { filename: string; rows: number } | null;
  onFileChange?: (file: File | null) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sha256, setSha256] = useState<string | null>(null);
  const [hashing, setHashing] = useState(false);
  const [dragging, setDragging] = useState(false);

  async function take(next: File | null) {
    setFile(next);
    setSha256(null);
    onFileChange?.(next);
    if (!next) return;
    setHashing(true);
    try {
      const digest = await crypto.subtle.digest("SHA-256", await next.arrayBuffer());
      setSha256(
        Array.from(new Uint8Array(digest))
          .map((byte) => byte.toString(16).padStart(2, "0"))
          .join(""),
      );
    } catch {
      // crypto.subtle needs a secure context; the upload still works without a
      // local hash, and the backend records the authoritative one either way.
      setSha256(null);
    } finally {
      setHashing(false);
    }
  }

  return (
    <div>
      <span className="text-sm font-medium text-ink">
        {label}
        {required && !existing && <span className="text-danger-ink"> *</span>}
      </span>
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
      {existing && !file && (
        <p className="mt-1 text-xs text-success-ink">
          Already on file: {existing.filename} ({existing.rows} row
          {existing.rows === 1 ? "" : "s"}). Choose a file below only to replace it.
        </p>
      )}

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          void take(event.dataTransfer.files[0] ?? null);
        }}
        className={cn(
          "mt-1.5 rounded-lg border border-dashed px-4 py-5 text-center",
          dragging ? "border-accent bg-success-tint" : "border-border bg-ground",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          name={name}
          accept={accept}
          required={required}
          onChange={(event) => void take(event.target.files?.[0] ?? null)}
          className="sr-only"
          id={`file-${name}`}
        />
        <label
          htmlFor={`file-${name}`}
          className="btn inline-flex cursor-pointer items-center rounded-lg bg-surface px-4 py-2 text-sm font-medium text-ink ring-1 ring-border ring-inset hover:bg-ground"
        >
          Choose a file
        </label>
        <p className="mt-2 text-xs text-muted">or drop it here</p>
      </div>

      {file && (
        <dl className="mt-2 space-y-1 rounded-lg bg-ground px-3 py-2 text-xs">
          <div className="flex justify-between gap-3">
            <dt className="text-muted">File</dt>
            <dd className="truncate font-medium text-ink">{file.name}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted">Size</dt>
            <dd className="tnum text-ink">{file.size.toLocaleString()} bytes</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="shrink-0 text-muted">SHA-256</dt>
            <dd className="truncate font-mono text-ink" title={sha256 ?? undefined}>
              {hashing ? "computing…" : (sha256 ?? "not available in this browser")}
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}
