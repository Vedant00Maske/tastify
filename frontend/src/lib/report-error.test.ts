import { afterEach, describe, expect, it, vi } from "vitest";

import { reportError } from "./report-error";

describe("reportError", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the message, path and digest once, without the query string", () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState(null, "", "/playlists/abc?token=secret#x");
    const error = Object.assign(new Error("Boom while rendering"), {
      digest: "12345",
    });

    reportError(error);
    reportError(error); // the same message is reported once per page load

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/client-errors$/);
    expect(init.keepalive).toBe(true);
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({
      kind: "render",
      message: "Error: Boom while rendering",
      path: "/playlists/abc",
      digest: "12345",
    });
  });

  it("classifies chunk loading failures and never throws", () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("offline"));
    vi.stubGlobal("fetch", fetchMock);
    expect(() =>
      reportError(
        new Error("ChunkLoadError: Loading chunk 7 failed"),
        "unhandled",
      ),
    ).not.toThrow();
    const body = JSON.parse(
      String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body),
    );
    expect(body.kind).toBe("chunk");
  });
});
