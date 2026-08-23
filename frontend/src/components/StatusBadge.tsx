export function statusBadge(status: string) {
  if (status === "COMPLETED" || status === "APPROVED" || status === "PARTIAL") {
    return status === "PARTIAL" ? "badge badge-warn" : "badge badge-ok";
  }
  if (status === "RUNNING" || status === "QUEUED" || status === "REVIEW_REQUIRED") {
    return "badge badge-warn";
  }
  if (status === "FAILED") return "badge badge-danger";
  return "badge badge-muted";
}
