import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo } from "react";

import {
  formatDuration,
  formatRelativeTime,
  formatAbsoluteTime,
  formatTokens,
  truncate,
} from "../lib/format";
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

function SortArrow({
  column,
  sort,
  order,
}: {
  column: string;
  sort: string;
  order: string;
}) {
  if (sort !== column) return null;
  return (
    <span className="ml-1 text-accent text-[10px]">
      {order === "asc" ? "\u25B2" : "\u25BC"}
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
          <span className="font-mono text-[11px] text-tertiary">
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
          <span className="inline-flex items-center rounded-md bg-accent-subtle px-1.5 py-0.5 text-[11px] font-medium text-accent">
            {info.getValue()}
          </span>
        ),
      }),
      columnHelper.accessor("task", {
        header: "Task",
        cell: (info) => (
          <span className="text-sm text-primary leading-snug">
            {truncate(info.getValue(), 55)}
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
          <span className="font-mono text-[11px] text-tertiary">
            {truncate(info.getValue(), 22)}
          </span>
        ),
      }),
      columnHelper.accessor("token_usage", {
        header: "Tokens",
        cell: (info) => {
          const usage = info.getValue();
          if (!usage) {
            return <span className="text-[11px] text-tertiary">&mdash;</span>;
          }
          return (
            <span className="font-mono text-[11px] tabular-nums text-secondary">
              <span className="text-primary">
                {formatTokens(usage.input_tokens)}
              </span>
              <span className="text-tertiary mx-0.5">/</span>
              <span>{formatTokens(usage.output_tokens)}</span>
            </span>
          );
        },
      }),
      columnHelper.accessor("duration_ms", {
        header: "Duration",
        cell: (info) => (
          <span className="font-mono text-[11px] tabular-nums text-secondary">
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

  const pageNumbers = useMemo(() => {
    const pages: number[] = [];
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, start + 4);
    for (let i = start; i <= end; i++) pages.push(i);
    return pages;
  }, [page, totalPages]);

  if (loading) {
    return (
      <div className="flex flex-col gap-px p-4">
        {Array.from({ length: 10 }, (_, i) => (
          <div
            key={i}
            className="h-10 animate-pulse rounded-md bg-surface"
            style={{ animationDelay: `${i * 50}ms` }}
          />
        ))}
      </div>
    );
  }

  if (traces.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-72 text-secondary gap-3">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-tertiary">
          <circle cx="11" cy="11" r="8" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <div className="text-sm">No traces found</div>
        <div className="text-xs text-tertiary">
          Try adjusting your filters or search query
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-x-auto">
        <table className="w-full">
          <thead className="sticky top-0 z-10 bg-background">
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
                      className={`cursor-pointer border-b border-border-strong px-4 py-2.5 text-[10px] font-semibold uppercase tracking-widest text-tertiary select-none hover:text-secondary transition-colors duration-150 ${
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
                  className={`group h-11 cursor-pointer border-b border-border transition-colors duration-150 ${
                    isSelected
                      ? "bg-accent-subtle border-l-2 border-l-accent"
                      : "hover:bg-surface"
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={`px-4 py-0 ${
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

      <div className="flex items-center justify-between border-t border-border px-4 py-2.5 shrink-0">
        <span className="text-xs text-tertiary tabular-nums">
          {rangeStart}&ndash;{rangeEnd}{" "}
          <span className="text-tertiary/60">of</span> {total}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={!hasPrev}
            onClick={() => onPageChange(page - 1)}
            className="rounded-md px-2 py-1 text-xs text-secondary hover:text-primary hover:bg-surface transition-colors duration-150 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
          {pageNumbers.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => onPageChange(p)}
              className={`min-w-[28px] rounded-md px-1.5 py-1 text-xs font-medium tabular-nums cursor-pointer transition-colors duration-150 ${
                p === page
                  ? "bg-accent text-white"
                  : "text-secondary hover:text-primary hover:bg-surface"
              }`}
            >
              {p}
            </button>
          ))}
          <button
            type="button"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
            className="rounded-md px-2 py-1 text-xs text-secondary hover:text-primary hover:bg-surface transition-colors duration-150 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
