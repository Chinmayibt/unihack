"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

type Mode = "csv" | "json-file" | "json-paste" | "single";

const SAMPLE_JSON = `{
  "mpn": "49-94-0013",
  "description": "4-1/2\\" Metal Cut-Off Wheel",
  "manufacturer": "Milwaukee",
  "e1_brand": "Milwaukee"
}`;

export default function UploadPage() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("csv");
  const [file, setFile] = useState<File | null>(null);
  const [jsonText, setJsonText] = useState(SAMPLE_JSON);
  const [single, setSingle] = useState({
    mpn: "",
    description: "",
    manufacturer: "",
    e1_brand: "",
    unilog_brand: "",
    dib_brand: "",
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [startJob, setStartJob] = useState(true);

  async function afterIngest(productIds: number[], label: string) {
    setMessage(label);
    if (!startJob) {
      router.push("/dashboard");
      return;
    }
    const job = await api.createJob({
      auto_start: true,
      product_ids: productIds.length ? productIds : undefined,
    });
    setMessage(`Job ${job.job_id} started with ${job.total} products.`);
    router.push("/dashboard");
  }

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      if (mode === "csv") {
        if (!file) throw new Error("Choose a CSV file first.");
        const uploaded = await api.uploadCsv(file);
        await afterIngest(
          uploaded.product_ids || [],
          `CSV ingested: ${uploaded.valid_rows} valid, ${uploaded.invalid_rows} invalid.`,
        );
        return;
      }
      if (mode === "json-file") {
        if (!file) throw new Error("Choose a JSON file first.");
        const uploaded = await api.uploadJsonFile(file);
        await afterIngest(
          uploaded.product_ids || [],
          `JSON file ingested: ${uploaded.valid_rows} valid, ${uploaded.invalid_rows} invalid.`,
        );
        return;
      }
      if (mode === "json-paste") {
        let payload: unknown;
        try {
          payload = JSON.parse(jsonText);
        } catch {
          throw new Error("Paste valid JSON (object or array).");
        }
        const uploaded = await api.uploadJson(payload);
        await afterIngest(
          uploaded.product_ids || [],
          `JSON ingested: ${uploaded.valid_rows} valid, ${uploaded.invalid_rows} invalid.`,
        );
        return;
      }
      if (!single.mpn.trim() || !single.description.trim()) {
        throw new Error("MPN and description are required.");
      }
      const uploaded = await api.uploadProduct({
        mpn: single.mpn.trim(),
        description: single.description.trim(),
        manufacturer: single.manufacturer.trim() || null,
        e1_brand: single.e1_brand.trim() || null,
        unilog_brand: single.unilog_brand.trim() || null,
        dib_brand: single.dib_brand.trim() || null,
      });
      await afterIngest(
        uploaded.product_ids || [],
        `Product ${single.mpn.trim()} ingested.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="fade-up mx-auto max-w-3xl">
      <section className="panel p-8">
        <h2 className="brand text-3xl">Product intake</h2>
        <p className="mt-2 text-[var(--muted)]">
          Choose how you want to enter catalog data — batch file, JSON, or one product.
        </p>

        <div className="mode-tabs mt-6">
          {(
            [
              ["csv", "CSV file"],
              ["json-file", "JSON file"],
              ["json-paste", "JSON paste"],
              ["single", "Single product"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              className={mode === id ? "btn btn-primary" : "btn btn-ghost"}
              onClick={() => {
                setMode(id);
                setFile(null);
                setError(null);
              }}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>

        <form className="mt-8 space-y-5" onSubmit={onSubmit}>
          {mode === "csv" || mode === "json-file" ? (
            <label className="block cursor-pointer rounded-2xl border border-dashed border-[var(--line)] bg-white/50 px-6 py-10 text-center transition hover:border-[var(--accent)]">
              <input
                accept={mode === "csv" ? ".csv,text/csv" : ".json,application/json"}
                className="hidden"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                type="file"
              />
              <div className="brand text-xl">
                {file ? file.name : mode === "csv" ? "Drop CSV / browse" : "Drop JSON / browse"}
              </div>
              <p className="mt-2 text-sm text-[var(--muted)]">
                {mode === "csv"
                  ? "Columns: Mfg_Part_Num, Part_Desc, brand fields, Part_Manuf."
                  : "Object or array. Keys may be mpn/description or CSV names."}
              </p>
            </label>
          ) : null}

          {mode === "json-paste" ? (
            <label className="field">
              <span>JSON object or array</span>
              <textarea
                onChange={(e) => setJsonText(e.target.value)}
                spellCheck={false}
                value={jsonText}
              />
            </label>
          ) : null}

          {mode === "single" ? (
            <div className="grid gap-4 md:grid-cols-2">
              <label className="field md:col-span-1">
                <span>MPN *</span>
                <input
                  onChange={(e) => setSingle({ ...single, mpn: e.target.value })}
                  value={single.mpn}
                />
              </label>
              <label className="field">
                <span>Manufacturer</span>
                <input
                  onChange={(e) => setSingle({ ...single, manufacturer: e.target.value })}
                  value={single.manufacturer}
                />
              </label>
              <label className="field md:col-span-2">
                <span>Description *</span>
                <input
                  onChange={(e) => setSingle({ ...single, description: e.target.value })}
                  value={single.description}
                />
              </label>
              <label className="field">
                <span>E1 Brand</span>
                <input
                  onChange={(e) => setSingle({ ...single, e1_brand: e.target.value })}
                  value={single.e1_brand}
                />
              </label>
              <label className="field">
                <span>Unilog Brand</span>
                <input
                  onChange={(e) => setSingle({ ...single, unilog_brand: e.target.value })}
                  value={single.unilog_brand}
                />
              </label>
              <label className="field md:col-span-2">
                <span>DIB Brand</span>
                <input
                  onChange={(e) => setSingle({ ...single, dib_brand: e.target.value })}
                  value={single.dib_brand}
                />
              </label>
            </div>
          ) : null}

          <label className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <input
              checked={startJob}
              onChange={(e) => setStartJob(e.target.checked)}
              type="checkbox"
            />
            Start processing job after ingest
          </label>

          {error ? <p className="text-[var(--danger)]">{error}</p> : null}
          {message ? <p className="text-[var(--ok)]">{message}</p> : null}

          <div className="flex flex-wrap gap-3">
            <button className="btn btn-primary" disabled={busy} type="submit">
              {busy ? "Working…" : "Ingest"}
            </button>
            <Link className="btn btn-ghost" href="/dashboard">
              Dashboard
            </Link>
          </div>
        </form>
      </section>
    </main>
  );
}
