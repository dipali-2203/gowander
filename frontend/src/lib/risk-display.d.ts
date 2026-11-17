export function riskAssessmentLabel(
  score: number | null | undefined,
  status: string | null | undefined,
): string;
export function riskProxyLabel(value: number, status: string | null | undefined): string;
export function riskDetailsLabel(score: number | null | undefined, status: string | null | undefined, metadata?: Record<string, unknown>): string;
