import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  API_BASE_URL,
  ApiError,
  apiFetch,
  errorMessage,
  withQuery,
} from "./api-client";

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls the same-origin API path with the session cookie", async () => {
    const fetchMock = mockFetch(
      Response.json({ status: "ok", version: "0.1.0" }),
    );

    await expect(apiFetch("/health")).resolves.toEqual({
      status: "ok",
      version: "0.1.0",
    });
    expect(API_BASE_URL).toBe("/api/v1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/health",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("serializes JSON bodies", async () => {
    const fetchMock = mockFetch(Response.json({ ok: true }));

    await apiFetch("/auth/login", {
      method: "POST",
      body: { email: "a@b.co", password: "x" },
    });
    const init = fetchMock.mock.calls[0][1];
    expect(init?.body).toBe('{"email":"a@b.co","password":"x"}');
    expect(init?.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("validates responses with the given schema", async () => {
    mockFetch(Response.json({ id: 42 }));

    const request = apiFetch("/users/me", {
      schema: z.object({ id: z.string() }),
    });
    await expect(request).rejects.toMatchObject({ status: 500 });
  });

  it("returns nothing for 204 responses", async () => {
    mockFetch(new Response(null, { status: 204 }));

    await expect(
      apiFetch("/auth/logout", { method: "POST" }),
    ).resolves.toBeUndefined();
  });

  it("returns nothing for accepted requests without a body", async () => {
    mockFetch(new Response("", { status: 202 }));

    await expect(
      apiFetch("/auth/email/verification", { method: "POST" }),
    ).resolves.toBeUndefined();
  });

  it("throws an ApiError with the API's message", async () => {
    mockFetch(
      Response.json({ detail: "invalid e-mail or password" }, { status: 401 }),
    );

    const request = apiFetch("/auth/login", { method: "POST", body: {} });
    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({
      status: 401,
      message: "invalid e-mail or password",
      isUnauthorized: true,
    });
  });

  it("falls back to a generic message when the body is not JSON", async () => {
    mockFetch(new Response("bad gateway", { status: 502 }));

    await expect(apiFetch("/health/ready")).rejects.toMatchObject({
      status: 502,
      message: "GET /health/ready failed with 502",
    });
  });
});

describe("errorMessage", () => {
  it("reads FastAPI validation errors", () => {
    const detail = [{ loc: ["body", "password"], msg: "too short" }];
    expect(errorMessage(detail, "fallback")).toBe("password: too short");
  });

  it("uses the fallback for unknown shapes", () => {
    expect(errorMessage({ nope: 1 }, "fallback")).toBe("fallback");
  });
});

describe("withQuery", () => {
  it("repeats array values and skips empty ones", () => {
    expect(
      withQuery("/x", { a: 1, b: ["p", "q"], c: undefined, d: null }),
    ).toBe("/x?a=1&b=p&b=q");
    expect(withQuery("/x", {})).toBe("/x");
  });
});
