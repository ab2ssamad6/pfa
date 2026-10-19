import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-600" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Unknown error";
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <p className="font-medium">Could not load data</p>
      <p className="mt-1">{msg}</p>
      {onRetry && (
        <button className="btn-secondary mt-3" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="p-6 text-center text-sm text-slate-500">{children}</div>;
}

/** Renders loading / error / content for a react-query result. */
export function QueryView<T>({
  q, children, empty, isEmpty,
}: {
  q: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  children: (data: T) => ReactNode;
  empty?: ReactNode;
  isEmpty?: (data: T) => boolean;
}) {
  if (q.isLoading) return <Loading />;
  if (q.error && q.data === undefined) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined) return <Loading />;
  if (isEmpty?.(q.data)) return <Empty>{empty ?? "No data yet."}</Empty>;
  return <>{children(q.data)}</>;
}
