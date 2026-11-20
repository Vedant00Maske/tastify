import { API_BASE_URL } from "@/services/api-client";

/**
 * Sends a browser error to the API (POST /client-errors, Milestone 7): no third-party script, no
 * personal data. Only the message (truncated), the page path without its query string and the
 * Next.js digest are sent; the same message is reported once per page load. Never throws.
 */
const reported = new Set<string>();

export type ClientErrorKind = "render" | "unhandled" | "chunk";

export function reportError(
  error: unknown,
  kind: ClientErrorKind = "render",
): void {
  try {
    if (typeof window === "undefined") return;
    const message = (
      error instanceof Error ? `${error.name}: ${error.message}` : String(error)
    ).slice(0, 500);
    if (reported.has(message) || reported.size >= 20) return;
    reported.add(message);
    const digest =
      error && typeof error === "object" && "digest" in error
        ? String((error as { digest?: unknown }).digest ?? "").slice(0, 64) ||
          null
        : null;
    const path =
      window.location.pathname.replace(/\s/g, "").slice(0, 200) || "/";
    void fetch(`${API_BASE_URL}/client-errors`, {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: /ChunkLoadError|Loading chunk/i.test(message) ? "chunk" : kind,
        message,
        path,
        digest,
      }),
    }).catch(() => undefined);
  } catch {
    // Reporting must never cause another error.
  }
}

/** Uncaught errors and rejected promises outside React rendering. Returns a cleanup. */
export function listenForUnhandledErrors(): () => void {
  const onError = (event: ErrorEvent) =>
    reportError(event.error ?? event.message, "unhandled");
  const onRejection = (event: PromiseRejectionEvent) =>
    reportError(event.reason, "unhandled");
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
