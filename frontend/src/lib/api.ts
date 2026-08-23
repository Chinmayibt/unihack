const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* ignore */
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export type JobSummary = {
  job_id: string;
  status: string;
  dataset_name: string | null;
  total: number;
  processed: number;
  approved: number;
  partial: number;
  review_required: number;
  failed: number;
  progress: number;
  worker_count: number;
  output_file: string | null;
  products_per_minute: number | null;
  success_rate: number | null;
  evidence_coverage: number | null;
  completeness: number | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
  review_breakdown?: Record<string, number>;
};

export type ReviewQueueItem = {
  id: number;
  product_id: number;
  mpn: string | null;
  issue_type: string;
  severity: string;
  attribute: string | null;
  current_value: string | null;
  reason: string;
  status: string;
};

export type ReviewDetail = {
  id: number;
  product_id: number;
  issue_type: string;
  severity: string;
  attribute: string | null;
  current_value: string | null;
  candidate_values: Array<{
    value: string;
    source: string | null;
    evidence_text: string | null;
  }>;
  evidence: string[];
  sources: Array<{
    id: number;
    url: string;
    title: string | null;
    source_type: string;
    authority_score: number;
  }>;
  reason: string;
  status: string;
  allowed_values: string[];
  product: {
    id: number;
    mpn: string;
    description: string;
    brand: string | null;
    manufacturer: string | null;
    status: string;
    classification: Record<string, unknown> | null;
  };
};

export type UploadResponse = {
  status: string;
  job_id: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  product_ids?: number[];
};

export type JobProduct = {
  product_id: number;
  mpn: string;
  description: string;
  item_status: string;
  product_status: string;
  brand: string | null;
  manufacturer: string | null;
};

export type ProductOutput = {
  product_id: number;
  mpn: string;
  processing_status: string;
  reviewed: boolean;
  approved_for_output: boolean;
  eligible_for_csv: boolean;
  eligibility_reason: string;
  assembled: {
    classification: {
      department?: string;
      class_name?: string;
      fine?: string;
      classpath?: string;
      confidence?: number;
      status?: string;
    } | null;
    attributes: Array<{
      label: string;
      normalized_value: string | null;
      normalized_uom: string | null;
      status: string;
    }>;
  };
  output: Record<string, string>;
  errors: string[];
};

export const api = {
  listJobs: () => request<JobSummary[]>("/jobs"),
  getJob: (id: string) => request<JobSummary>(`/jobs/${id}`),
  listJobProducts: (id: string, skip = 0, limit = 100) =>
    request<{ total: number; items: JobProduct[] }>(
      `/jobs/${id}/products?skip=${skip}&limit=${limit}`,
    ),
  getProductOutput: (productId: number) =>
    request<ProductOutput>(`/products/${productId}/output`),
  downloadJobCsv: async (jobId: string, filename: string) => {
    const res = await fetch(`${API_BASE}/jobs/${jobId}/output.csv`, {
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail ?? body);
      } catch {
        /* ignore */
      }
      throw new Error(detail || `Download failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },
  startJob: (id: string) =>
    request<JobSummary>(`/jobs/${id}/start`, { method: "POST" }),
  createJob: (body?: {
    auto_start?: boolean;
    product_ids?: number[];
    limit?: number;
  }) =>
    request<JobSummary>("/jobs", {
      method: "POST",
      body: JSON.stringify(body ?? { auto_start: true }),
    }),
  uploadCsv: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResponse>("/upload", { method: "POST", body: form });
  },
  uploadJsonFile: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadResponse>("/upload/json/file", {
      method: "POST",
      body: form,
    });
  },
  uploadJson: (payload: unknown) =>
    request<UploadResponse>("/upload/json", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadProduct: (payload: {
    mpn: string;
    description: string;
    manufacturer?: string | null;
    e1_brand?: string | null;
    unilog_brand?: string | null;
    dib_brand?: string | null;
  }) =>
    request<UploadResponse>("/upload/product", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listReviews: (status = "PENDING") =>
    request<{ total: number; items: ReviewQueueItem[] }>(
      `/review-queue?status=${encodeURIComponent(status)}`,
    ),
  getReview: (id: number) => request<ReviewDetail>(`/review-queue/${id}`),
  resolveReview: (
    id: number,
    payload: {
      decision: string;
      selected_value?: string | null;
      reviewed_by?: string;
      review_reason?: string | null;
    },
  ) =>
    request(`/review-queue/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  generateOutput: (jobId?: string) =>
    request<{
      status: string;
      output_file: string;
      approved: number;
      partial: number;
      review_pending: number;
      skipped: number;
    }>(`/output/generate${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`, {
      method: "POST",
    }),
};
