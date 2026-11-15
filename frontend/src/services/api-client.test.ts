import { afterEach, describe, expect, it, vi } from "vitest";

import type { HealthResponse } from "@/types/api";

import { API_BASE_URL, ApiError, apiFetch } from "./api-client";

function mockFetch(response: Response) {
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the API base URL with credentials and returns parsed JSON", async () => {
    const body: HealthResponse = { status: "ok", version: "0.1.0" };
    const fetchMock = mockFetch(Response.json(body));

    await expect(apiFetch<HealthResponse>("/health")).resolves.toEqual(body);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE_URL}/health`,
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("throws an ApiError carrying the status code for non-2xx responses", async () => {
    mockFetch(new Response(null, { status: 503 }));

    const request = apiFetch("/health/ready");

    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({ status: 503 });
  });
});
