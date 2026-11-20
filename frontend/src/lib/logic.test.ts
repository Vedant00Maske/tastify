import { describe, expect, it } from "vitest";

import { percent, pointsChange, weekLabel } from "@/features/discovery/format";
import {
  loginSchema,
  registerSchema,
  safeNext,
} from "@/features/auth/auth-forms";
import { playlistSchema } from "@/features/playlists/playlist-dialogs";
import { currentTrack, listenLinks, usePlayer } from "@/stores/player";

import { formatDuration, greeting, hashString, pluralize } from "./utils";

describe("formatting", () => {
  it("formats durations", () => {
    expect(formatDuration(222_000)).toBe("3:42");
    expect(formatDuration(3_720_000)).toBe("1 h 2 min");
    expect(formatDuration(null)).toBeNull();
    expect(formatDuration(0)).toBeNull();
  });

  it("greets by time of day", () => {
    expect(greeting(new Date(2026, 0, 1, 8))).toBe("Good morning");
    expect(greeting(new Date(2026, 0, 1, 14))).toBe("Good afternoon");
    expect(greeting(new Date(2026, 0, 1, 21))).toBe("Good evening");
  });

  it("pluralizes", () => {
    expect(pluralize(1, "track")).toBe("1 track");
    expect(pluralize(2, "track")).toBe("2 tracks");
  });

  it("hashes deterministically", () => {
    expect(hashString("soniqueo")).toBe(hashString("soniqueo"));
    expect(hashString("a")).not.toBe(hashString("b"));
  });

  it("formats analytics values", () => {
    expect(weekLabel("2026-11-02")).toMatch(/2/);
    expect(pointsChange(0.04)).toBe("+4 pts");
    expect(pointsChange(-0.031)).toBe("−3 pts");
    expect(percent(0.5)).toBe("50%");
  });
});

describe("auth forms", () => {
  it("only follows same-site redirects after login", () => {
    expect(safeNext("/playlists/1")).toBe("/playlists/1");
    expect(safeNext("//evil.example")).toBe("/home");
    expect(safeNext("https://evil.example")).toBe("/home");
    expect(safeNext(null)).toBe("/home");
  });

  it("refuses redirects that browsers would read as another site", () => {
    // Browsers treat a backslash like a slash: "/\\evil.example" is "//evil.example".
    expect(safeNext("/\\evil.example")).toBe("/home");
    expect(safeNext("/\\/evil.example")).toBe("/home");
    expect(safeNext("/%5Cevil.example")).toBe("/%5Cevil.example");
    expect(safeNext("/\tevil")).toBe("/home");
    expect(safeNext("/x\n/y")).toBe("/home");
    expect(safeNext("/search?q=a#b")).toBe("/search?q=a#b");
    expect(safeNext("javascript:alert(1)")).toBe("/home");
  });

  it("validates registration", () => {
    const valid = {
      email: "listener@example.com",
      password: "long enough pass",
      confirm: "long enough pass",
      accept_terms: true,
    };
    expect(registerSchema.safeParse(valid).success).toBe(true);
    expect(
      registerSchema.safeParse({ ...valid, confirm: "different" }).success,
    ).toBe(false);
    expect(
      registerSchema.safeParse({
        ...valid,
        password: "short",
        confirm: "short",
      }).success,
    ).toBe(false);
    expect(
      registerSchema.safeParse({ ...valid, accept_terms: false }).success,
    ).toBe(false);
    expect(registerSchema.safeParse({ ...valid, email: "nope" }).success).toBe(
      false,
    );
  });

  it("validates login", () => {
    expect(
      loginSchema.safeParse({ email: "a@example.com", password: "" }).success,
    ).toBe(false);
  });

  it("validates playlist names", () => {
    expect(
      playlistSchema.safeParse({ name: "  ", description: "" }).success,
    ).toBe(false);
    expect(
      playlistSchema.safeParse({ name: "Night", description: "" }).success,
    ).toBe(true);
  });
});

describe("player store", () => {
  const tracks = ["a", "b", "c", "d"].map((id) => ({
    id,
    title: id.toUpperCase(),
    artist: "X",
  }));

  it("plays, steps through and clears a queue", () => {
    const player = usePlayer.getState();
    player.play(tracks, 1);
    expect(currentTrack(usePlayer.getState())?.id).toBe("b");
    usePlayer.getState().next();
    usePlayer.getState().next();
    usePlayer.getState().next();
    expect(currentTrack(usePlayer.getState())?.id).toBe("d");
    usePlayer.getState().previous();
    expect(currentTrack(usePlayer.getState())?.id).toBe("c");
    usePlayer.getState().clear();
    expect(currentTrack(usePlayer.getState())).toBeNull();
  });

  it("shuffles without losing or duplicating tracks", () => {
    usePlayer.getState().playShuffled(tracks);
    const ids = usePlayer.getState().queue.map((t) => t.id);
    expect([...ids].sort()).toEqual(["a", "b", "c", "d"]);
    usePlayer.getState().play(tracks, 2);
    usePlayer.getState().shuffle();
    expect(currentTrack(usePlayer.getState())?.id).toBe("c");
  });

  it("links out to listen elsewhere", () => {
    const links = listenLinks({ id: "1", title: "Creep", artist: "Radiohead" });
    expect(links.map((l) => l.label)).toEqual(["YouTube", "MusicBrainz"]);
    expect(links[0].href).toContain("Radiohead%20Creep");
  });
});
