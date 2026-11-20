import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FeedbackButtons } from "@/components/feedback/feedback-buttons";
import { TrackCard } from "@/components/music/cards";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { ExplorationPicker } from "@/features/settings/exploration-picker";
import { useRecentSearches } from "@/hooks/use-recent-searches";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/home",
  useSearchParams: () => new URLSearchParams(),
}));

// Radix measures elements with ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PROFILE = {
  user_id: "00000000-0000-4000-8000-000000000001",
  profile_version: "v1",
  genre_affinity: [],
  artist_affinity: [],
  negative_artists: [],
  listening_frequency: {},
  exploration_preference: 0.5,
  exploration_mode: null,
  discovery_target: 0.5,
  history_size: 1,
  interaction_count: 1,
  last_event_at: null,
};

describe("FeedbackButtons", () => {
  let fetchMock: ReturnType<typeof vi.fn<typeof fetch>>;

  beforeEach(() => {
    fetchMock = vi
      .fn<typeof fetch>()
      .mockImplementation(async () =>
        Response.json(
          { recorded: 1, duplicates: 0, profile: PROFILE },
          { status: 201 },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("records like, dislike and save as interaction events", async () => {
    render(
      <FeedbackButtons
        trackId="00000000-0000-4000-8000-0000000000aa"
        title="Creep"
        state={{ liked: false, disliked: false, saved: false }}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Like Creep" }));
    fireEvent.click(screen.getByRole("button", { name: "Dislike Creep" }));
    fireEvent.click(screen.getByRole("button", { name: "Save Creep" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const events = fetchMock.mock.calls.map(([url, init]) => {
      expect(url).toBe("/api/v1/interactions");
      return JSON.parse(String(init?.body)).events[0].event_type;
    });
    expect(events).toEqual(["like", "dislike", "save"]);
  });

  it("undoes active feedback", async () => {
    render(
      <FeedbackButtons
        trackId="00000000-0000-4000-8000-0000000000aa"
        title="Creep"
        state={{ liked: true, disliked: false, saved: true }}
      />,
      { wrapper },
    );

    const unlike = screen.getByRole("button", { name: "Unlike Creep" });
    expect(unlike).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(unlike);
    fireEvent.click(
      screen.getByRole("button", { name: "Remove Creep from saved" }),
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const events = fetchMock.mock.calls.map(
      ([, init]) => JSON.parse(String(init?.body)).events[0].event_type,
    );
    expect(events).toEqual(["unlike", "unsave"]);
  });
});

describe("TrackCard", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverStub);
    vi.stubGlobal(
      "fetch",
      vi
        .fn<typeof fetch>()
        .mockImplementation(async () => Response.json({ playlists: [] })),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows the track, its reason, discovery badge and a play control", () => {
    const onPlay = vi.fn();
    render(
      <TrackCard
        track={{
          id: "00000000-0000-4000-8000-0000000000bb",
          title: "Ocean Man",
          artist: "Ween",
          artistId: "00000000-0000-4000-8000-0000000000cc",
          reason: "New artist for you: Ween",
          discovery: true,
        }}
        state={{ liked: false, disliked: false, saved: false }}
        onPlay={onPlay}
      />,
      { wrapper },
    );

    expect(screen.getByRole("link", { name: "Ocean Man" })).toHaveAttribute(
      "href",
      "/tracks/00000000-0000-4000-8000-0000000000bb",
    );
    expect(screen.getByRole("link", { name: "Ween" })).toHaveAttribute(
      "href",
      "/artists/00000000-0000-4000-8000-0000000000cc",
    );
    expect(screen.getByText("New artist for you: Ween")).toBeInTheDocument();
    expect(screen.getByText("New artist")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Play Ocean Man by Ween" }),
    );
    expect(onPlay).toHaveBeenCalledOnce();
  });
});

describe("ExplorationPicker", () => {
  beforeEach(() => vi.stubGlobal("ResizeObserver", ResizeObserverStub));
  afterEach(() => vi.unstubAllGlobals());

  it("describes the chosen balance and can hand it to SONIQUEO", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ExplorationPicker value="explorer" onChange={onChange} />,
    );
    expect(
      screen.getByText("Unexpected discoveries", { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("slider")).toHaveAttribute(
      "aria-valuetext",
      expect.stringContaining("80% new"),
    );

    fireEvent.click(
      screen.getByRole("button", { name: /Let SONIQUEO learn it/ }),
    );
    expect(onChange).toHaveBeenCalledWith(null);

    rerender(<ExplorationPicker value={null} onChange={onChange} />);
    expect(screen.getByText("Learned from you")).toBeInTheDocument();
  });
});

describe("states", () => {
  it("renders empty and error states", () => {
    const retry = vi.fn();
    render(
      <>
        <EmptyState title="No playlists yet" description="Create one." />
        <ErrorState message="Could not load." onRetry={retry} />
      </>,
    );
    expect(screen.getByText("No playlists yet")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});

describe("useRecentSearches", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    try {
      window.localStorage.clear();
    } catch {
      // ignore
    }
  });

  it("keeps the latest distinct terms first", () => {
    const { result } = renderHook(() => useRecentSearches());
    act(() => {
      result.current.clear();
      result.current.add("radiohead");
      result.current.add("ween");
      result.current.add("Radiohead");
      result.current.add("x");
    });
    expect(result.current.terms).toEqual(["Radiohead", "ween"]);
    act(() => result.current.remove("ween"));
    expect(result.current.terms).toEqual(["Radiohead"]);
  });

  it("still works when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => useRecentSearches());
    act(() => {
      result.current.clear();
      result.current.add("blocked storage");
    });
    expect(result.current.terms).toEqual(["blocked storage"]);
  });
});
