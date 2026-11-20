import type { z } from "zod";

/**
 * The browser talks to the API on its own origin: `/api/v1/*` is forwarded to FastAPI by the
 * Next.js proxy (src/proxy.ts), so the session cookie is first-party. NEXT_PUBLIC_API_URL can
 * point elsewhere for special setups (inlined at build time).
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

/** The human-readable message of a FastAPI error body ({"detail": ...}). */
export function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: unknown; loc?: unknown[] };
    if (typeof first.msg === "string") {
      const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
      return typeof field === "string" ? `${field}: ${first.msg}` : first.msg;
    }
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    const message = (detail as { message: unknown }).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

type Query = Record<
  string,
  string | number | boolean | string[] | null | undefined
>;

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value == null) continue;
    for (const item of Array.isArray(value) ? value : [value])
      params.append(key, String(item));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

interface Options<T> extends Omit<RequestInit, "body"> {
  body?: unknown;
  schema?: z.ZodType<T>;
}

/** The viewer's IANA time zone, for context-aware recommendations (ADR-019). */
function timezoneHeader(): Record<string, string> {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone ? { "X-Timezone": zone } : {};
  } catch {
    return {};
  }
}

/**
 * Typed JSON request to the TASTIFY API. Sends cookies (session auth), serializes JSON bodies,
 * validates the response with `schema` when given, and throws ApiError with the API's message.
 */
export async function apiFetch<T>(
  path: string,
  options: Options<T> = {},
): Promise<T> {
  const { body, schema, headers, ...init } = options;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...timezoneHeader(),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    let detail: unknown;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail;
    } catch {
      detail = undefined;
    }
    const fallback = `${init.method ?? "GET"} ${path} failed with ${response.status}`;
    throw new ApiError(response.status, errorMessage(detail, fallback), detail);
  }
  if (response.status === 204) return undefined as T;

  // 202 Accepted (e-mail requests, error reports) may come without a body.
  const text = await response.text();
  if (!text) return undefined as T;
  const data: unknown = JSON.parse(text);
  if (!schema) return data as T;
  const parsed = schema.safeParse(data);
  if (!parsed.success) {
    throw new ApiError(
      500,
      `Unexpected response from ${path}`,
      parsed.error.issues,
    );
  }
  return parsed.data;
}
