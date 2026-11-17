/** Human-readable labels that never present missing risk data as zero risk. */
export function riskAssessmentLabel(score, status) {
  if (
    typeof score !== "number" ||
    !status ||
    ["unavailable", "partial", "not_applicable"].includes(status)
  ) {
    return "Risk data unavailable";
  }
  if (score === 0) {
    return `0% reported disruption risk (${status}; not a safety guarantee)`;
  }
  return `${Math.round(score * 100)}% estimated disruption risk (${status})`;
}

export function riskProxyLabel(value, status) {
  if (!status || status === "unavailable" || status === "partial") {
    return "Risk data unavailable · known-risk proxy used";
  }
  return value === 0
    ? "0% known-risk proxy (not a safety rating)"
    : `${Math.round(value * 100)}% risk proxy`;
}
