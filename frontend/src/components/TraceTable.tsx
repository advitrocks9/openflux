import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo } from "react";

import { formatDuration, formatRelativeTime, formatAbsoluteTime, formatTokens, truncate } from "../lib/format";
import type { Trace } from "../types";
import { StatusBadge } from "./StatusBadge";

interface TraceTableProps {
  traces: Trace[];
  loading: boolean;
  total: number;
  page: number;
  pageSize: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPageChange: (page: number) => void;
  onSort: (column: string, order: "asc" | "desc") => void;
  sort: string;
  order: string;
}

const columnHelper = createColumnHelper<Trace>();

function SortArrow({ column, sort, order }: { column: string; sort: string; order: string }) {
  if (sort !== column) return null;
  return (
    <span className="ml-1 text-accent">
      {order === "asc" ? "\u2191" : "\u2193"}
    </span>
  );
}

export function TraceTable({
  traces,
  loading,
  total,
  page,
  pageSize,
  selectedId,
  onSelect,
  onPageChange,
  onSort,
  sort,
  order,
}: TraceTableProps) {
  const columns = useMemo(
    () => [
      columnHelper.accessor("id", {
        header: "ID",
        cell: (info) => (
          <span className="font-mono text-xs text-tertiary">
            {info.getValue().slice(-8)}
          </span>
        ),
      }),
      columnHelper.accessor("timestamp", {
        header: "When",
        cell: (info) => {
          const iso = info.getValue();
          return (
            <time
              dateTime={iso}
              title={formatAbsoluteTime(iso)}
              className="text-xs text-secondary"
            >
              {formatRelativeTime(iso)}
            </time>
          );
        },
      }),
      columnHelper.accessor("agent", {
        header: "Agent",
        cell: (info) => (
          <span className="rounded bg-accent-subtle px-1.5 py-0.5 text-xs text-accent">
            {info.getValue()}
          </span>
        ),
      }),
      columnHelper.accessor("task", {
        header: "Task",
        cell: (info) => (
          <span className="text-sm text-primary">
            {truncate(info.getValue(), 50)}
          </span>
        ),
      }),
      columnHelper.accessor("status", {
        header: "Status",
        cell: (info) => <StatusBadge status={info.getValue()} />,
      }),
      columnHelper.accessor("model", {
        header: "Model",
        cell: (info) => (
          <span className="font-mono text-xs text-tertiary">
            {truncate(info.getValue(), 20)}
          </span>
        ),
      }),
      columnHelper.accessor("token_usage", {
        header: "Tokens",
        cell: (info) => {
          const usage = info.getValue();
          if (!usage) {
            return <span className="text-xs text-tertiary">--</span>;
          }
          return (
            <span className="font-mono text-xs tabular-nums">
              {formatTokens(usage.input_tokens)} / {formatTokens(usage.output_tokens)}
            </span>
          );
        },
      }),
      columnHelper.accessor("duration_ms", {
        header: "Duration",
        cell: (info) => (
          <span className="font-mono text-xs tabular-nums">
            {formatDuration(info.getValue())}
          </span>
        ),
      }),
    ],
    [],
  );

  const table = useReactTable({
    data: traces,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  const handleSort = (columnId: string) => {
    const nextOrder = sort === columnId && order === "asc" ? "desc" : "asc";
    onSort(columnId, nextOrder);
  };

  const rangeStart = (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, total);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const hasPrev = page > 1;
  const hasNext = page < totalPages;

  if (loading) {
    return (
      <div className="flex flex-col gap-1 p-4">
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="h-10 animate-pulse rounded bg-surface" />
        ))}
      </div>
    );
  }

  if (traces.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-secondary">
        No traces found
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const isRightAligned =
                    header.column.id === "token_usage" ||
                    header.column.id === "duration_ms";
                  return (
                    <th
                      key={header.id}
                      onClick={() => handleSort(header.column.id)}
                      className={`cursor-pointer border-b border-border-strong px-3 py-2 text-xs font-medium uppercase tracking-wider text-tertiary select-none ${
                        isRightAligned ? "text-right" : "text-left"
                      }`}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                      <SortArrow
                        column={header.column.id}
                        sort={sort}
                        order={order}
                      />
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const isSelected = row.original.id === selectedId;
              const isRightAligned = (cellId: string) =>
                cellId.includes("token_usage") ||
                cellId.includes("duration_ms");

              return (
                <tr
                  key={row.id}
                  onClick={() => onSelect(row.original.id)}
                  className={`h-10 cursor-pointer border-b border-border transition-colors duration-150 hover:bg-accent-subtle ${
                    isSelected ? "border-l-2 border-l-accent bg-accent-subtle" : ""
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={`px-3 py-0 text-sm ${
                        isRightAligned(cell.column.id) ? "text-right" : ""
                      }`}
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      <div className="flex items-center justify-between border-t border-border px-3 py-2">
        <span className="text-xs text-secondary">
          Showing {rangeStart}&ndash;{rangeEnd} of {total} traces
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() => onPageChange(page - 1)}
            className="rounded border border-border px-2.5 py-1 text-xs text-secondary transition-colors duration-150 hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
          >
            Prev
          </button>
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
            className="rounded border border-border px-2.5 py-1 text-xs text-secondary transition-colors duration-150 hover:bg-surface disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
