"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ReviewQueueItem } from "@/lib/api";

export default function ReviewQueuePage() {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("PENDING");
  const [issueFilter, setIssueFilter] = useState("ALL");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setError(null);
      const data = await api.listReviews(filter);
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review queue");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const issueTypes = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of items) {
      counts.set(item.issue_type, (counts.get(item.issue_type) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [items]);

  const visible = items.filter(
    (item) => issueFilter === "ALL" || item.issue_type === issueFilter,
  );

  return (
    <main className="fade-up space-y-6">
      <section className="panel p-6 md:p-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="brand text-3xl">Human review</h2>
            <p className="mt-2 text-[var(--muted)]">
              {total} items in queue · showing {visible.length}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {["PENDING", "APPROVED", "REJECTED", "UNKNOWN"].map((status) => (
              <button
                key={status}
                className={filter === status ? "btn btn-primary" : "btn btn-ghost"}
                onClick={() => setFilter(status)}
                type="button"
              >
                {status}
              </button>
            ))}
          </div>
        </div>

        {issueTypes.length > 0 ? (
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              className={issueFilter === "ALL" ? "btn btn-primary" : "btn btn-ghost"}
              onClick={() => setIssueFilter("ALL")}
              type="button"
            >
              All issues
            </button>
            {issueTypes.map(([type, count]) => (
              <button
                key={type}
                className={issueFilter === type ? "btn btn-primary" : "btn btn-ghost"}
                onClick={() => setIssueFilter(type)}
                type="button"
              >
                {type} ({count})
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {error ? (
        <div className="panel p-4 text-[var(--danger)]">{error}</div>
      ) : null}

      <section className="panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>MPN</th>
                <th>Issue</th>
                <th>Attribute</th>
                <th>Reason</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5} className="text-[var(--muted)]">
                    Loading queue…
                  </td>
                </tr>
              ) : null}
              {!loading &&
                visible.slice(0, 100).map((item) => (
                  <tr key={item.id}>
                    <td className="font-medium">{item.mpn || `#${item.product_id}`}</td>
                    <td>
                      <span className="badge badge-warn">{item.issue_type}</span>
                    </td>
                    <td>{item.attribute || "—"}</td>
                    <td className="max-w-md text-sm text-[var(--muted)]">
                      {item.reason}
                    </td>
                    <td>
                      <Link className="btn btn-ghost" href={`/review/${item.id}`}>
                        Review
                      </Link>
                    </td>
                  </tr>
                ))}
              {!loading && visible.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-[var(--muted)]">
                    No review items for this filter.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {visible.length > 100 ? (
          <p className="px-5 py-3 text-sm text-[var(--muted)]">
            Showing first 100 of {visible.length}. Narrow by issue type for the rest.
          </p>
        ) : null}
      </section>
    </main>
  );
}
