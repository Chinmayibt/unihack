"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { OutputPreview } from "@/components/OutputPreview";
import { statusBadge } from "@/components/StatusBadge";
import {
  api,
  type JobProduct,
  type JobSummary,
  type ProductOutput,
} from "@/lib/api";

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const [job, setJob] = useState<JobSummary | null>(null);
  const [products, setProducts] = useState<JobProduct[]>([]);
  const [productTotal, setProductTotal] = useState(0);
  const [preview, setPreview] = useState<ProductOutput | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [summary, listed] = await Promise.all([
        api.getJob(jobId),
        api.listJobProducts(jobId),
      ]);
      setJob(summary);
      setProducts(listed.items);
      setProductTotal(listed.total);
      if (listed.items.length === 1) {
        setPreview(await api.getProductOutput(listed.items[0].product_id));
      } else {
        setPreview(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load job");
    }
  }, [jobId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function download() {
    if (!job) return;
    setBusy(true);
    try {
      await api.downloadJobCsv(job.job_id, job.dataset_name || "delivery");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!job) return;
    setBusy(true);
    try {
      await api.generateOutput(job.job_id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generate failed");
    } finally {
      setBusy(false);
    }
  }

  if (!job && !error) {
    return <p className="text-[var(--muted)]">Loading job…</p>;
  }

  if (!job) {
    return (
      <div className="panel p-6 text-[var(--danger)]">
        {error}
        <div className="mt-4">
          <Link className="btn btn-ghost" href="/dashboard">
            Back to dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <main className="fade-up space-y-6">
      {error ? (
        <div className="panel p-4 text-[var(--danger)]">{error}</div>
      ) : null}

      <section className="panel p-6 md:p-8">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
          <div>
            <Link className="text-sm text-[var(--muted)] hover:underline" href="/dashboard">
              ← All jobs
            </Link>
            <h2 className="brand mt-2 text-3xl">{job.dataset_name || job.job_id}</h2>
            <p className="mt-1 font-mono text-xs text-[var(--muted)]">{job.job_id}</p>
          </div>
          <span className={statusBadge(job.status)}>{job.status}</span>
        </div>

        <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
          <div className="metric">
            <strong>{job.total}</strong>
            <span>Products</span>
          </div>
          <div className="metric">
            <strong>{job.processed}</strong>
            <span>Processed</span>
          </div>
          <div className="metric">
            <strong>{job.approved}</strong>
            <span>Approved</span>
          </div>
          <div className="metric">
            <strong>{job.partial}</strong>
            <span>Partial</span>
          </div>
          <div className="metric">
            <strong>{job.review_required}</strong>
            <span>Needs review</span>
          </div>
          <div className="metric">
            <strong>{job.failed}</strong>
            <span>Failed</span>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          <button
            className="btn btn-primary"
            disabled={busy || job.status !== "COMPLETED" || job.total <= 0}
            onClick={() => void download()}
            type="button"
          >
            {busy ? "Working…" : "Download output CSV"}
          </button>
          <button
            className="btn btn-ghost"
            disabled={busy || job.status !== "COMPLETED"}
            onClick={() => void generate()}
            type="button"
          >
            Generate output CSV
          </button>
          <Link className="btn btn-ghost" href="/review">
            Review queue
          </Link>
        </div>
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-[var(--line)] px-5 py-4">
          <h3 className="brand text-xl">Products</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {productTotal} in this job · click a row for the delivery record
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>MPN</th>
                <th>Description</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {products.map((item) => (
                <tr key={item.product_id}>
                  <td className="font-medium">{item.mpn}</td>
                  <td className="max-w-xl text-sm text-[var(--muted)]">
                    {item.description}
                  </td>
                  <td>
                    <span className={statusBadge(item.product_status)}>
                      {item.product_status}
                    </span>
                  </td>
                  <td>
                    <Link
                      className="btn btn-ghost"
                      href={`/dashboard/${job.job_id}/products/${item.product_id}`}
                    >
                      View output
                    </Link>
                  </td>
                </tr>
              ))}
              {products.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-[var(--muted)]">
                    No products in this job.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {productTotal > products.length ? (
          <p className="px-5 py-3 text-sm text-[var(--muted)]">
            Showing first {products.length} of {productTotal}.
          </p>
        ) : null}
      </section>

      {preview ? (
        <section className="panel p-6 md:p-8">
          <h3 className="brand text-2xl">Delivery output</h3>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Assembled record for {preview.mpn}
          </p>
          <div className="mt-6">
            <OutputPreview data={preview} />
          </div>
        </section>
      ) : null}
    </main>
  );
}
