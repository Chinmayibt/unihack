"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { statusBadge } from "@/components/StatusBadge";
import { api, type JobSummary } from "@/lib/api";

export default function DashboardPage() {
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setJobs(await api.listJobs());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(id);
  }, [load]);

  const latest = jobs[0];

  async function generate(jobId: string) {
    setBusy(jobId);
    try {
      await api.generateOutput(jobId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Output generate failed");
    } finally {
      setBusy(null);
    }
  }

  async function start(jobId: string) {
    setBusy(jobId);
    try {
      await api.startJob(jobId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start job");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="fade-up space-y-6">
      {error ? (
        <div className="panel border-[color-mix(in_oklab,var(--danger)_35%,var(--line))] p-4 text-[var(--danger)]">
          {error}
        </div>
      ) : null}

      {latest ? (
        <section className="panel p-6 md:p-8">
          <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-sm text-[var(--muted)]">Latest job</p>
              <Link href={`/dashboard/${latest.job_id}`}>
                <h2 className="brand mt-1 text-2xl hover:underline">
                  {latest.dataset_name || latest.job_id}
                </h2>
              </Link>
              <p className="mt-1 font-mono text-xs text-[var(--muted)]">{latest.job_id}</p>
            </div>
            <span className={statusBadge(latest.status)}>{latest.status}</span>
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-6">
            <div className="metric">
              <strong>{latest.total}</strong>
              <span>Products</span>
            </div>
            <div className="metric">
              <strong>{latest.processed}</strong>
              <span>Processed</span>
            </div>
            <div className="metric">
              <strong>{latest.approved}</strong>
              <span>Approved</span>
            </div>
            <div className="metric">
              <strong>{latest.partial}</strong>
              <span>Partial</span>
            </div>
            <div className="metric">
              <strong>{latest.review_required}</strong>
              <span>Needs review</span>
            </div>
            <div className="metric">
              <strong>{latest.failed}</strong>
              <span>Failed</span>
            </div>
          </div>

          <div className="mt-6 h-2 overflow-hidden rounded-full bg-[var(--line)]">
            <div
              className="h-full rounded-full bg-[var(--accent)] transition-all duration-500"
              style={{ width: `${Math.min(100, latest.progress || 0)}%` }}
            />
          </div>

          <div className="mt-6 flex flex-wrap gap-6 text-sm text-[var(--muted)]">
            <span>
              Evidence coverage{" "}
              <b className="text-[var(--ink)]">
                {((latest.evidence_coverage || 0) * 100).toFixed(1)}%
              </b>
            </span>
            <span>
              Completeness{" "}
              <b className="text-[var(--ink)]">
                {((latest.completeness || 0) * 100).toFixed(1)}%
              </b>
            </span>
            <span>
              Pace{" "}
              <b className="text-[var(--ink)]">
                {(latest.products_per_minute || 0).toFixed(1)} / min
              </b>
            </span>
          </div>

          {latest.review_breakdown && Object.keys(latest.review_breakdown).length > 0 ? (
            <div className="mt-6 flex flex-wrap gap-2">
              {Object.entries(latest.review_breakdown).map(([key, value]) => (
                <span key={key} className="badge badge-muted">
                  {key}: {value}
                </span>
              ))}
            </div>
          ) : null}

          <div className="mt-8 flex flex-wrap gap-3">
            <Link className="btn btn-primary" href={`/dashboard/${latest.job_id}`}>
              View details & output
            </Link>
            <Link className="btn btn-ghost" href="/review">
              Open review queue
            </Link>
            {latest.status === "QUEUED" ? (
              <button
                className="btn btn-ghost"
                disabled={busy === latest.job_id || latest.total <= 0}
                onClick={() => void start(latest.job_id)}
                type="button"
              >
                {busy === latest.job_id ? "Starting…" : "Start job"}
              </button>
            ) : (
              <button
                className="btn btn-ghost"
                disabled={busy === latest.job_id || latest.status !== "COMPLETED"}
                onClick={() => void generate(latest.job_id)}
                type="button"
              >
                {busy === latest.job_id ? "Generating…" : "Generate output CSV"}
              </button>
            )}
            <Link className="btn btn-ghost" href="/upload">
              Open intake
            </Link>
          </div>
        </section>
      ) : (
        <section className="panel p-8 text-center">
          <h2 className="brand text-2xl">No jobs yet</h2>
          <p className="mt-2 text-[var(--muted)]">
            Upload a product CSV to start enrichment.
          </p>
          <Link className="btn btn-primary mt-6" href="/upload">
            Upload dataset
          </Link>
        </section>
      )}

      <section className="panel overflow-hidden">
        <div className="border-b border-[var(--line)] px-5 py-4">
          <h3 className="brand text-xl">All jobs</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>Dataset</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Approved</th>
                <th>Review</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <Link className="block hover:underline" href={`/dashboard/${job.job_id}`}>
                      <div className="font-medium">{job.dataset_name || "Untitled"}</div>
                      <div className="font-mono text-xs text-[var(--muted)]">{job.job_id}</div>
                    </Link>
                  </td>
                  <td>
                    <span className={statusBadge(job.status)}>{job.status}</span>
                  </td>
                  <td>
                    {job.processed}/{job.total} ({job.progress.toFixed(1)}%)
                  </td>
                  <td>{job.approved}</td>
                  <td>{job.review_required}</td>
                  <td>
                    <Link className="btn btn-ghost" href={`/dashboard/${job.job_id}`}>
                      View
                    </Link>
                  </td>
                </tr>
              ))}
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-[var(--muted)]">
                    No processing jobs found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
