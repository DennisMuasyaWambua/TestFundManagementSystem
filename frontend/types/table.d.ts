import type { RowData } from "@tanstack/react-table";

declare module "@tanstack/react-table" {
  /** Column metadata the DataTable understands. */
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Right-align this column and use tabular figures: it holds a number. */
    numeric?: boolean;
    /** Carried so the generic parameters are used, keeping the declaration valid. */
    accessorHint?: (row: TData) => TValue;
  }
}
