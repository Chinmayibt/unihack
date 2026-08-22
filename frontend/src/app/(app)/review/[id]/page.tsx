"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, type ReviewDetail } from "@/lib/api";

export default function ReviewDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const reviewId = Number(params.id);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.getReview(reviewId);
      setDetail(data);
      setSelected(data.current_value || data.candidate_values[0]?.value || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load review");
    }
  }, [reviewId]);

  useEffect(() => {
    if (Number.isFinite(reviewId)) void load();
  }, [load, reviewId]);

  async function resolve(decision: string) {
    setBusy(true);
    try {
      await api.resolveReview(reviewId, {
        decision,
        selected_value:
          decision === "SELECT_CANDIDATE" || decision === "APPROVE_CURRENT"
            ? selected || detail?.current_value || null
            : null,
        reviewed_by: "demo-reviewer",
      });
      router.push("/review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resolve failed");
    } finally {
      setBusy(false);
    }
  }

  if (!detail && !error) {
    return <p className="text-[var(--muted)]">Loading review…</p>;
  }

  if (!detail) {
    return (
      <div className="panel p-6 text-[var(--danger)]">
        {error}
        <div className="mt-4">
          <Link className="btn btn-ghost" href="/review">
            Back
          </Link>
        </div>
      </div>
    );
  }

  const classpath =
    (detail.product.classification?.classpath as string | undefined) ||
    (detail.product.classification?.fine as string | undefined) ||
    "—";

  return (
    <main className="fade-up grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
      <section className="panel p-6 md:p-8">
        <p className="text-sm uppercase tracking-[0.14em] text-[var(--muted)]">
          Product #{detail.product_id}
        </p>
        <h2 className="brand mt-2 text-3xl">{detail.product.mpn}</h2>
        <p className="mt-3 text-lg text-[var(--ink)]">{detail.product.description}</p>

        <dl className="mt-6 grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">Brand</dt>
            <dd>{detail.product.brand || "—"}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Manufacturer</dt>
            <dd>{detail.product.manufacturer || "—"}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Classification</dt>
            <dd>{classpath}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Status</dt>
            <dd>{detail.product.status}</dd>
          </div>
        </dl>

        <div className="mt-8 rounded-2xl border border-[var(--line)] bg-white/60 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge badge-warn">{detail.issue_type}</span>
            <span className="badge badge-muted">{detail.severity}</span>
          </div>
          <p className="mt-3 font-medium">{detail.attribute || "Product issue"}</p>
          <p className="mt-2 text-sm text-[var(--muted)]">{detail.reason}</p>
          {detail.current_value ? (
            <p className="mt-3 text-sm">
              Current value: <b>{detail.current_value}</b>
            </p>
          ) : null}
        </div>
      </section>

      <section className="panel space-y-5 p-6 md:p-8">
        <h3 className="brand text-2xl">Decision</h3>

        {(detail.candidate_values.length > 0 || detail.allowed_values.length > 0) && (
          <label className="block text-sm">
            <span className="text-[var(--muted)]">Selected value</span>
            <select
              className="mt-2 w-full rounded-xl border border-[var(--line)] bg-white px-3 py-2"
              onChange={(e) => setSelected(e.target.value)}
              value={selected}
            >
              {detail.current_value ? (
                <option value={detail.current_value}>{detail.current_value} (current)</option>
              ) : null}
              {detail.candidate_values.map((c) => (
                <option key={`c-${c.value}`} value={c.value}>
                  {c.value}
                </option>
              ))}
              {detail.allowed_values.map((value) => (
                <option key={`a-${value}`} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        )}

        {detail.evidence.length > 0 ? (
          <div>
            <h4 className="text-sm uppercase tracking-[0.08em] text-[var(--muted)]">
              Evidence
            </h4>
            <ul className="mt-2 space-y-2 text-sm">
              {detail.evidence.map((line) => (
                <li key={line} className="rounded-xl bg-white/70 px-3 py-2">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {detail.sources.length > 0 ? (
          <div>
            <h4 className="text-sm uppercase tracking-[0.08em] text-[var(--muted)]">
              Sources
            </h4>
            <ul className="mt-2 space-y-2 text-sm">
              {detail.sources.map((source) => (
                <li key={source.id}>
                  <a
                    className="text-[var(--accent-deep)] underline-offset-2 hover:underline"
                    href={source.url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {source.title || source.url}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {error ? <p className="text-[var(--danger)]">{error}</p> : null}

        <div className="flex flex-wrap gap-2 pt-2">
          <button
            className="btn btn-primary"
            disabled={busy}
            onClick={() => void resolve("APPROVE_CURRENT")}
            type="button"
          >
            Approve
          </button>
          <button
            className="btn btn-ghost"
            disabled={busy || !selected}
            onClick={() => void resolve("SELECT_CANDIDATE")}
            type="button"
          >
            Save selected
          </button>
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void resolve("MARK_UNKNOWN")}
            type="button"
          >
            Mark unknown
          </button>
          <button
            className="btn btn-ghost"
            disabled={busy}
            onClick={() => void resolve("REJECT_ATTRIBUTE")}
            type="button"
          >
            Reject
          </button>
          <Link className="btn btn-ghost" href="/review">
            Back
          </Link>
        </div>
      </section>
    </main>
  );
}
