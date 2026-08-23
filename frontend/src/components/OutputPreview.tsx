import type { ProductOutput } from "@/lib/api";

const HIGHLIGHT_KEYS = [
  "Mfg_Part_Num",
  "Part_Desc",
  "BRAND_NAME",
  "MANUFACTURER_NAME",
  "Classpath",
  "SHORT_DESC",
  "MFR URL",
  "WIDTH",
  "WIDTH_UOM",
  "LENGTH",
  "LENGTH_UOM",
  "Selling Qty",
  "Selling UOM",
];

export function OutputPreview({ data }: { data: ProductOutput }) {
  const classification = data.assembled.classification;
  const filled = Object.entries(data.output).filter(([, value]) => value.trim());

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge badge-warn">{data.processing_status}</span>
        <span className="badge badge-muted">{data.eligibility_reason}</span>
        {data.eligible_for_csv ? (
          <span className="badge badge-ok">In delivery CSV</span>
        ) : (
          <span className="badge badge-muted">Not in CSV</span>
        )}
      </div>

      <dl className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <dt className="text-[var(--muted)]">MPN</dt>
          <dd className="font-medium">{data.mpn}</dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">Classpath</dt>
          <dd>{classification?.classpath || data.output.Classpath || "—"}</dd>
        </div>
        {HIGHLIGHT_KEYS.filter((key) => data.output[key]).map((key) => (
          <div key={key}>
            <dt className="text-[var(--muted)]">{key}</dt>
            <dd className="break-all">{data.output[key]}</dd>
          </div>
        ))}
      </dl>

      {data.assembled.attributes.length > 0 ? (
        <div>
          <h4 className="text-sm uppercase tracking-[0.08em] text-[var(--muted)]">
            Attributes
          </h4>
          <div className="mt-3 overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Value</th>
                  <th>UOM</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.assembled.attributes.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    <td>{row.normalized_value || "—"}</td>
                    <td>{row.normalized_uom || "—"}</td>
                    <td>{row.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      <details>
        <summary className="cursor-pointer text-sm text-[var(--muted)]">
          All filled delivery fields ({filled.length})
        </summary>
        <dl className="mt-3 grid gap-2 text-sm">
          {filled.map(([key, value]) => (
            <div key={key} className="grid gap-1 md:grid-cols-[220px_1fr]">
              <dt className="text-[var(--muted)]">{key}</dt>
              <dd className="break-all">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
