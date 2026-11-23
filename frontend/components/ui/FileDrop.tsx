"use client";

import { useRef, useState } from "react";

import { cn } from "@/lib/cn";
import { parseCsvPreview } from "@/lib/csv";

/**
 * A file picker that shows the SHA-256 of what was chosen, plus a row preview.
 *
 * The hash is computed in the browser and displayed before anything is uploaded, so
 * the person uploading a wet-signed letter or a custodian statement can compare it
 * with the hash the system records -- and see for themselves that the file stored is
 * the file they picked.  The backend computes its own hash; this one is for the eye.
 *
 * The preview parses the file as CSV entirely in the browser -- nothing is sent
 * anywhere -- so a wrong column order or a stray header shows up before the file
 * is staged server-side at all.
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
  const [preview, setPreview] = useState<{
    headers: string[];
    rows: string[][];
    totalRows: number;
  } | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  async function take(next: File | null) {
    setFile(next);
    setSha256(null);
    setPreview(null);
    setPreviewError(null);
    onFileChange?.(next);
    if (!next) return;

    try {
      const text = await next.text();
      const parsed = parseCsvPreview(text);
      if (parsed.headers.length === 0) {
        setPreviewError("Could not find a header row to preview.");
      } else {
        setPreview(parsed);
      }
    } catch {
      setPreviewError("Could not read this file as text, so there's no preview.");
    }

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

      {previewError && <p className="mt-2 text-xs text-muted">{previewError}</p>}

      {preview && (
        <div className="mt-2 overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-xs">
            <thead className="bg-ground">
              <tr>
                {preview.headers.map((header, index) => (
                  <th
                    key={index}
                    scope="col"
                    className="px-2.5 py-1.5 text-left font-semibold tracking-wide text-muted uppercase"
                  >
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className="border-t border-border">
                  {preview.headers.map((_, columnIndex) => (
                    <td key={columnIndex} className="truncate px-2.5 py-1.5">
                      {row[columnIndex] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-border bg-ground px-2.5 py-1.5 text-xs text-muted">
            Showing {preview.rows.length} of {preview.totalRows} row
            {preview.totalRows === 1 ? "" : "s"}.
          </p>
        </div>
      )}
    </div>
  );
}
