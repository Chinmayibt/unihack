"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { OutputPreview } from "@/components/OutputPreview";
import { api, type ProductOutput } from "@/lib/api";

export default function JobProductOutputPage() {
  const params = useParams<{ id: string; productId: string }>();
  const jobId = params.id;
  const productId = Number(params.productId);
  const [data, setData] = useState<ProductOutput | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      setData(await api.getProductOutput(productId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load output");
    }
  }, [productId]);

  useEffect(() => {
    if (Number.isFinite(productId)) void load();
  }, [load, productId]);

  if (!data && !error) {
    return <p className="text-[var(--muted)]">Loading output…</p>;
  }

  if (!data) {
    return (
      <div className="panel p-6 text-[var(--danger)]">
        {error}
        <div className="mt-4">
          <Link className="btn btn-ghost" href={`/dashboard/${jobId}`}>
            Back to job
          </Link>
        </div>
      </div>
    );
  }

  return (
    <main className="fade-up space-y-6">
      <section className="panel p-6 md:p-8">
        <Link className="text-sm text-[var(--muted)] hover:underline" href={`/dashboard/${jobId}`}>
          ← Back to job
        </Link>
        <p className="mt-3 text-sm uppercase tracking-[0.14em] text-[var(--muted)]">
          Product #{data.product_id}
        </p>
        <h2 className="brand mt-2 text-3xl">{data.mpn}</h2>
        <p className="mt-3 text-lg">{data.output.Part_Desc || "—"}</p>
        <div className="mt-8">
          <OutputPreview data={data} />
        </div>
      </section>
    </main>
  );
}
