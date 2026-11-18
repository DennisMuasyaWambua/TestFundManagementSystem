"use client";

import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";

/**
 * The one grid every screen uses: sortable, filterable, paginated, CSV-exportable,
 * and horizontally scrollable on a narrow screen.
 *
 * It stays a real table with a real header cell per column, because a screen reader
 * has to be able to announce which balance belongs to which client.
 */
export function DataTable<T>({
  columns,
  rows,
  filterPlaceholder = "Filter rows",
  pageSize = 25,
  csvName,
  emptyMessage = "Nothing to show.",
  initialSorting = [],
  rowHref,
}: {
  columns: ColumnDef<T, string>[];
  rows: T[];
  filterPlaceholder?: string;
  pageSize?: number;
  /** When set, a CSV button appears and exports the rows as filtered and sorted. */
  csvName?: string;
  emptyMessage?: string;
  initialSorting?: SortingState;
  rowHref?: (row: T) => string | null;
}) {
  const router = useRouter();
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [filter, setFilter] = useState("");

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  const visibleRows = table.getRowModel().rows;
  const filteredCount = table.getFilteredRowModel().rows.length;

  const downloadCsv = useCallback(() => {
    if (!csvName) return;
    const headers = table
      .getVisibleFlatColumns()
      .map((column) => String(column.columnDef.header ?? column.id));
    const body = table.getFilteredRowModel().rows.map((row) =>
      row.getVisibleCells().map((cell) => {
        const value = cell.getValue();
        return value === null || value === undefined ? "" : String(value);
      }),
    );
    const quote = String.fromCharCode(34);
    const escape = (cell: string) => {
      const needsQuotes = cell.includes(quote) || cell.includes(",") || cell.includes("\n");
      if (!needsQuotes) return cell;
      return quote + cell.split(quote).join(quote + quote) + quote;
    };
    const text = [headers, ...body].map((line) => line.map(escape).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = csvName + ".csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }, [csvName, table]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <label className="flex-1 sm:max-w-xs">
          <span className="sr-only">{filterPlaceholder}</span>
          <input
            type="search"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder={filterPlaceholder}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm placeholder:text-muted"
          />
        </label>
        <div className="flex items-center gap-2">
          <p className="text-xs text-muted">
            {filteredCount === rows.length
              ? `${rows.length} rows`
              : `${filteredCount} of ${rows.length} rows`}
          </p>
          {csvName && (
            <Button
              variant="secondary"
              type="button"
              onClick={downloadCsv}
              className="px-3 py-1.5"
            >
              Download CSV
            </Button>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-ground">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => {
                  const sortable = header.column.getCanSort();
                  const direction = header.column.getIsSorted();
                  const numeric = header.column.columnDef.meta?.numeric ?? false;
                  return (
                    <th
                      key={header.id}
                      scope="col"
                      aria-sort={
                        direction === "asc"
                          ? "ascending"
                          : direction === "desc"
                            ? "descending"
                            : sortable
                              ? "none"
                              : undefined
                      }
                      className={cn(
                        "border-b border-border px-3 py-2 text-xs font-semibold tracking-wide text-muted uppercase",
                        numeric && "text-right",
                      )}
                    >
                      {sortable ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex min-h-0 items-center gap-1 hover:text-ink"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span aria-hidden="true" className="text-[0.65rem]">
                            {direction === "asc" ? "^" : direction === "desc" ? "v" : "-"}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {visibleRows.length === 0 && (
              <tr>
                <td
                  colSpan={table.getVisibleFlatColumns().length}
                  className="px-3 py-8 text-center text-sm text-muted"
                >
                  {emptyMessage}
                </td>
              </tr>
            )}
            {visibleRows.map((row) => {
              const href = rowHref ? rowHref(row.original) : null;
              return (
                <tr
                  key={row.id}
                  onClick={href ? () => router.push(href) : undefined}
                  className={cn(
                    "border-b border-border last:border-0",
                    href && "cursor-pointer hover:bg-ground",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={cn(
                        "px-3 py-2.5 align-top",
                        cell.column.columnDef.meta?.numeric && "tnum text-right",
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {table.getPageCount() > 1 && (
        <div className="mt-3 flex items-center justify-between gap-2">
          <Button
            variant="secondary"
            type="button"
            className="px-3 py-1.5"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            Previous
          </Button>
          <p className="text-xs text-muted">
            Page {table.getState().pagination.pageIndex + 1} of {table.getPageCount()}
          </p>
          <Button
            variant="secondary"
            type="button"
            className="px-3 py-1.5"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}
