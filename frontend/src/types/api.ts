// Mirrors backend/app/schemas/health.py.
export type CheckStatus = "ok" | "unavailable";

export interface HealthResponse {
  status: "ok";
  version: string;
}

export interface ReadinessResponse {
  status: CheckStatus;
  checks: Record<string, CheckStatus>;
}
