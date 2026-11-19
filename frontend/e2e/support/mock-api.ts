import type { BrowserContext, Page, Route } from "@playwright/test";

/**
 * An in-memory TASTIFY API for end-to-end tests: every /api/v1 request from the browser is
 * answered here, so the journeys run without the backend, database or models. Responses follow
 * the backend schemas (the app validates them with Zod, so a drift fails the test).
 */

const uuid = (n: number) =>
  `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const USER_ID = uuid(1);
export const SESSION_COOKIE = "tastify_session";

interface Track {
  id: string;
  title: string;
  artist: string;
  artist_id: string;
  album_title: string;
  duration_ms: number;
  release_year: number;
}

const ARTISTS = [
  { id: uuid(100), name: "Radiohead", genres: ["alternative rock"] },
  { id: uuid(101), name: "Ween", genres: ["alternative rock"] },
  { id: uuid(102), name: "Tame Impala", genres: ["psychedelic rock"] },
];

export const TRACKS: Track[] = [
  ["Creep", 0],
  ["Karma Police", 0],
  ["Ocean Man", 1],
  ["Push th' Little Daisies", 1],
  ["The Less I Know the Better", 2],
  ["Let It Happen", 2],
].map(([title, a], i) => ({
  id: uuid(200 + i),
  title: title as string,
  artist: ARTISTS[a as number].name,
  artist_id: ARTISTS[a as number].id,
  album_title: `${title} (single)`,
  duration_ms: 200_000 + i * 1000,
  release_year: 1995 + i,
}));

const MOODS = [
  {
    key: "midnight-drive",
    title: "Midnight Drive",
    description: "Synths and steady motion after dark.",
    genres: ["synthwave"],
  },
  {
    key: "deep-focus",
    title: "Deep Focus",
    description: "Unobtrusive, textured and steady.",
    genres: ["ambient"],
  },
];

function summary(track: Track) {
  return {
    id: track.id,
    title: track.title,
    artist: track.artist,
    duration_ms: track.duration_ms,
    release_year: track.release_year,
    artist_id: track.artist_id,
    album_title: track.album_title,
    artwork_url: null,
  };
}

function item(track: Track, reason: string, discovery = false) {
  return {
    track_id: track.id,
    title: track.title,
    artist: track.artist,
    artist_id: track.artist_id,
    album: track.album_title,
    artwork_url: null,
    score: 0.9,
    reason,
    discovery,
    sources: [
      {
        source: "content_based",
        retrieval_score: 0.8,
        rank: 1,
        model_version: "content-test",
      },
    ],
  };
}

let requestCounter = 0;
function response(strategy: string, tracks: Track[], reason: string) {
  requestCounter += 1;
  return {
    request_id: uuid(9000 + requestCounter),
    model_version: "test",
    model_versions: {},
    strategy,
    recommendations: tracks.map((t, i) => item(t, reason, i % 2 === 1)),
  };
}

function personalized(strategy: string, tracks: Track[], reason: string) {
  return {
    ...response(strategy, tracks, reason),
    user_id: USER_ID,
    profile_version: "taste-profile-test",
    ranker: "weighted-hybrid",
    composition: {
      familiar: Math.ceil(tracks.length / 2),
      discovery: Math.floor(tracks.length / 2),
      discovery_target: 0.5,
      exploration_mode: "balanced",
      diversity_policy: "for_you",
    },
    candidate_sources: [],
  };
}

export class MockApi {
  signedIn = false;
  onboarded = false;
  email = "listener@example.com";
  password = "a long enough password";
  displayName: string | null = "Listener";
  preferences = {
    exploration_mode: "balanced" as string | null,
    personalization_enabled: true,
    preferred_artists: [] as { artist_id: string; name: string }[],
    excluded_artists: [] as { artist_id: string; name: string }[],
    preferred_genres: [] as string[],
    excluded_genres: [] as string[],
    preferred_moods: [] as string[],
    updated_at: null as string | null,
  };
  feedback = new Map<
    string,
    { liked: boolean; disliked: boolean; saved: boolean }
  >();
  events: { track_id: string; event_type: string }[] = [];
  playlists = new Map<
    string,
    {
      id: string;
      name: string;
      description: string | null;
      kind: string;
      collection: string | null;
      generator: Record<string, unknown> | null;
      trackIds: string[];
    }
  >();
  unhandled: string[] = [];
  deleted = false;
  customPrompts: Record<string, unknown>[] = [];
  // Integrations (Milestone 5): ListenBrainz connects with a token; nothing else is configured.
  listenbrainzToken = "lb-token-0123456789";
  lbConnected = false;
  lastImport: Record<string, unknown> | null = null;
  exportsByPlaylist = new Map<string, Record<string, unknown>[]>();
  private playlistCounter = 0;

  constructor(private readonly context: BrowserContext) {}

  /** Start signed in (and onboarded): sets the session cookie the proxy checks. */
  async signIn({ onboarded = true } = {}) {
    this.signedIn = true;
    this.onboarded = onboarded;
    await this.setCookie();
  }

  private async setCookie() {
    await this.context.addCookies([
      {
        name: SESSION_COOKIE,
        value: "e2e-session",
        url: "http://localhost:3000",
      },
    ]);
  }

  private me() {
    return {
      id: USER_ID,
      email: this.email,
      display_name: this.displayName,
      created_at: "2026-11-01T10:00:00Z",
      onboarding_completed: this.onboarded,
    };
  }

  private playlistSummary(id: string) {
    const p = this.playlists.get(id)!;
    const tracks = p.trackIds.map((t) => TRACKS.find((x) => x.id === t)!);
    return {
      id: p.id,
      name: p.name,
      description: p.description,
      kind: p.kind,
      collection: p.collection,
      track_count: tracks.length,
      duration_ms: tracks.reduce((sum, t) => sum + t.duration_ms, 0) || null,
      artwork_urls: [],
      created_at: "2026-11-10T10:00:00Z",
      updated_at: "2026-11-10T10:00:00Z",
    };
  }

  private playlistDetail(id: string) {
    const p = this.playlists.get(id)!;
    return {
      ...this.playlistSummary(id),
      generator: p.generator,
      tracks: p.trackIds.map((t, position) => ({
        ...summary(TRACKS.find((x) => x.id === t)!),
        position,
        added_at: "2026-11-10T10:00:00Z",
      })),
    };
  }

  createPlaylist(
    name: string,
    trackIds: string[] = [],
    generator: Record<string, unknown> | null = null,
  ) {
    this.playlistCounter += 1;
    const id = uuid(5000 + this.playlistCounter);
    const ids = trackIds.length
      ? trackIds
      : generator
        ? TRACKS.slice(0, 4).map((t) => t.id)
        : [];
    this.playlists.set(id, {
      id,
      name,
      description: null,
      kind: generator ? "generated" : "manual",
      collection: (generator?.collection as string | undefined) ?? null,
      generator,
      trackIds: ids,
    });
    return id;
  }

  private taste() {
    return {
      overview:
        "Your listening centres on alternative rock, with Radiohead at its heart.",
      events: this.events.length + 12,
      genres: [
        { genre: "alternative rock", score: 1 },
        { genre: "psychedelic rock", score: 0.4 },
      ],
      artists: [
        { artist_id: ARTISTS[0].id, name: "Radiohead", score: 1, playbacks: 9 },
      ],
      trends: Array.from({ length: 12 }, (_, i) => ({
        week_start: `2026-${String(8 + Math.floor(i / 4)).padStart(2, "0")}-${String(1 + (i % 4) * 7).padStart(2, "0")}`,
        playbacks: i * 2,
        distinct_tracks: i,
        new_artists: i % 3,
      })),
      emerging: [
        {
          genre: "psychedelic rock",
          recent_share: 0.3,
          earlier_share: 0.1,
          change: 0.2,
        },
      ],
      fading: [],
      discovery: {
        new_artists_30d: 2,
        new_genres_30d: 1,
        saved_tracks: 1,
        liked_tracks: 3,
        exploration_preference: 0.4,
        discovery_target: 0.5,
      },
    };
  }

  async install(page: Page) {
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private async handle(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = request.method();
    const body = request.postData()
      ? JSON.parse(request.postData()!)
      : undefined;
    const json = (data: unknown, status = 200) =>
      route.fulfill({ status, json: data });
    const noContent = () => route.fulfill({ status: 204, body: "" });
    const error = (status: number, detail: string) =>
      route.fulfill({ status, json: { detail } });

    // --- auth -------------------------------------------------------------------------------
    if (path === "/auth/register" && method === "POST") {
      this.email = body.email;
      this.password = body.password;
      this.displayName = body.display_name ?? null;
      this.signedIn = true;
      this.onboarded = false;
      await this.setCookie();
      return json(this.me(), 201);
    }
    if (path === "/auth/login" && method === "POST") {
      if (body.email !== this.email || body.password !== this.password) {
        return error(401, "invalid e-mail or password");
      }
      this.signedIn = true;
      await this.setCookie();
      return json(this.me());
    }
    if (path === "/auth/logout" && method === "POST") {
      this.signedIn = false;
      await this.context.clearCookies();
      return noContent();
    }

    // Public catalogue and recommendation endpoints work signed out too.
    const isPublic =
      path.startsWith("/recommendations/moods") ||
      path.startsWith("/recommendations/popular") ||
      path.startsWith("/genres");
    if (!this.signedIn && !isPublic) return error(401, "not signed in");

    // --- account ----------------------------------------------------------------------------
    if (path === "/users/me" && method === "GET") return json(this.me());
    if (path === "/users/me" && method === "PATCH") {
      if ("display_name" in body) this.displayName = body.display_name;
      if (body.onboarding_completed) this.onboarded = true;
      return json(this.me());
    }
    if (path === "/users/me" && method === "DELETE") {
      if (body?.password !== this.password)
        return error(403, "password is wrong");
      this.signedIn = false;
      this.deleted = true;
      await this.context.clearCookies();
      return noContent();
    }
    if (path === "/users/me/preferences" && method === "GET")
      return json(this.preferences);
    if (path === "/users/me/preferences" && method === "PUT") {
      const name = (id: string) => ({
        artist_id: id,
        name: ARTISTS.find((a) => a.id === id)?.name ?? "Artist",
      });
      this.preferences = {
        ...this.preferences,
        ...body,
        preferred_artists: body.preferred_artists.map(name),
        excluded_artists: body.excluded_artists.map(name),
        updated_at: "2026-11-17T10:00:00Z",
      };
      return json(this.preferences);
    }
    if (path === "/users/me/taste") return json(this.taste());
    if (path === "/users/me/taste-profile") {
      return json({
        user_id: USER_ID,
        profile_version: "taste-profile-test",
        genre_affinity: [{ genre: "alternative rock", score: 1 }],
        artist_affinity: [
          { artist_id: ARTISTS[0].id, name: "Radiohead", score: 1 },
        ],
        negative_artists: [],
        listening_frequency: {},
        exploration_preference: 0.4,
        exploration_mode: this.preferences.exploration_mode,
        discovery_target: 0.5,
        history_size: 6,
        interaction_count: this.events.length,
        last_event_at: null,
      });
    }

    // --- catalogue --------------------------------------------------------------------------
    if (path === "/genres") {
      return json({
        genres: [
          { name: "alternative rock", tracks: 1200 },
          { name: "psychedelic rock", tracks: 300 },
        ],
      });
    }
    if (path === "/artists/search") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const results = ARTISTS.filter((a) =>
        a.name.toLowerCase().includes(q),
      ).map((a) => ({
        id: a.id,
        name: a.name,
        area: null,
        genres: a.genres,
        track_count: 2,
        artwork_url: null,
      }));
      return json({ query: q, results });
    }
    if (path === "/tracks/search") {
      const q = (url.searchParams.get("q") ?? "").toLowerCase();
      const results = TRACKS.filter((t) =>
        `${t.title} ${t.artist}`.toLowerCase().includes(q),
      ).map(summary);
      return json({ query: q, results });
    }
    const trackMatch = path.match(/^\/tracks\/([0-9a-f-]{36})$/);
    if (trackMatch) {
      const track = TRACKS.find((t) => t.id === trackMatch[1]);
      if (!track) return error(404, "track not found");
      return json({
        ...summary(track),
        isrc: null,
        credits: [
          { artist_id: track.artist_id, name: track.artist, join_phrase: "" },
        ],
        album: {
          id: uuid(300),
          title: track.album_title,
          album_type: "Single",
          release_year: track.release_year,
        },
        genres: [
          {
            name: "alternative rock",
            weight: 1,
            level: "track",
            source: "musicbrainz",
          },
        ],
      });
    }
    const artistMatch = path.match(/^\/artists\/([0-9a-f-]{36})$/);
    if (artistMatch) {
      const artist = ARTISTS.find((a) => a.id === artistMatch[1]);
      if (!artist) return error(404, "artist not found");
      return json({
        id: artist.id,
        name: artist.name,
        artist_type: "Group",
        area: "United Kingdom",
        begin_year: 1985,
        genres: artist.genres.map((name) => ({ name, weight: 1 })),
        track_count: 2,
      });
    }

    // --- recommendations --------------------------------------------------------------------
    if (path === "/recommendations/moods") return json({ moods: MOODS });
    const moodMatch = path.match(/^\/recommendations\/mood\/(.+)$/);
    if (moodMatch) {
      const mood = MOODS.find((m) => m.key === moodMatch[1]);
      if (!mood) return error(404, "unknown mood");
      const exclude = new Set(url.searchParams.getAll("exclude"));
      const tracks = TRACKS.filter((t) => !exclude.has(t.id)).slice(0, 3);
      return json({
        ...response("mood", tracks, `Fits ${mood.title}`),
        mood,
        personalized: true,
      });
    }
    if (path === "/recommendations/for-you")
      return json(
        personalized(
          "personalized",
          TRACKS,
          "Because you like alternative rock",
        ),
      );
    if (path === "/recommendations/hidden-gems")
      return json(
        personalized("hidden_gems", TRACKS.slice(2, 5), "A hidden gem"),
      );
    if (path === "/recommendations/custom" && method === "POST") {
      const prompt = String(body.prompt);
      if (/glorb/i.test(prompt)) {
        return route.fulfill({
          status: 422,
          json: {
            detail: {
              message:
                "No genre, mood or artist in this prompt matched the catalogue.",
              code: "prompt_not_understood",
              ignored: ["glorbic"],
            },
          },
        });
      }
      this.customPrompts.push(body);
      const exclude = new Set<string>(body.exclude ?? []);
      const tracks = TRACKS.filter((t) => !exclude.has(t.id)).slice(0, 3);
      return json({
        ...response("custom", tracks, "alternative rock (fit 0.92)"),
        prompt,
        personalized: true,
        interpretation: {
          genres: ["alternative rock"],
          excluded_genres: ["metal"],
          moods: [],
          artists: [{ id: ARTISTS[0].id, name: "Radiohead" }],
          excluded_artists: [],
          tempo: [120, null],
          danceability: [null, null],
          years: [null, null],
          popularity: null,
          exploration_level: body.exploration_level ?? null,
          ignored: ["vibes"],
          summary: "alternative rock; near Radiohead; over 120 BPM; no metal",
        },
      });
    }
    if (path === "/recommendations/surprise")
      return json(personalized("surprise", [TRACKS[4]], "A surprise for you"));
    if (path === "/recommendations/because-you-listened") {
      return json({
        sections: [
          {
            seed: summary(TRACKS[0]),
            source: "collaborative_item",
            recommendations: [item(TRACKS[1], "Listeners of Creep play this")],
          },
        ],
      });
    }
    if (path.startsWith("/recommendations/popular"))
      return json(
        response(
          url.searchParams.get("kind") === "trending" ? "trending" : "popular",
          TRACKS.slice(0, 4),
          "Popular right now",
        ),
      );
    if (path.startsWith("/recommendations/genre/"))
      return json(response("genre", TRACKS.slice(0, 2), "Top in the genre"));
    if (path.startsWith("/recommendations/artist-radio/"))
      return json(
        response("artist_radio", TRACKS.slice(1, 4), "On this radio"),
      );
    if (path.startsWith("/recommendations/artist/"))
      return json(
        response("similar_artists", TRACKS.slice(3, 6), "Related artist"),
      );
    if (path.startsWith("/recommendations/similar/"))
      return json(
        response("similar_tracks", TRACKS.slice(2, 6), "Similar sound"),
      );

    // --- interactions -----------------------------------------------------------------------
    if (path === "/interactions" && method === "POST") {
      for (const event of body.events) {
        this.events.push(event);
        const state = this.feedback.get(event.track_id) ?? {
          liked: false,
          disliked: false,
          saved: false,
        };
        const effects: Record<string, Partial<typeof state>> = {
          like: { liked: true, disliked: false },
          unlike: { liked: false },
          dislike: { disliked: true, liked: false },
          undislike: { disliked: false },
          save: { saved: true },
          unsave: { saved: false },
        };
        this.feedback.set(event.track_id, {
          ...state,
          ...effects[event.event_type],
        });
      }
      return json(
        {
          recorded: body.events.length,
          duplicates: 0,
          profile: await this.profileFor(),
        },
        201,
      );
    }
    if (path === "/interactions/state") {
      const states: Record<string, unknown> = {};
      for (const id of url.searchParams.getAll("track_id")) {
        states[id] = this.feedback.get(id) ?? {
          liked: false,
          disliked: false,
          saved: false,
        };
      }
      return json({ states });
    }
    if (path === "/interactions/history") {
      const types = url.searchParams.getAll("event_type");
      const items = this.events
        .filter((e) => !types.length || types.includes(e.event_type))
        .map((e, i) => ({
          id: uuid(7000 + i),
          track_id: e.track_id,
          event_type: e.event_type,
          occurred_at: "2026-11-17T09:00:00Z",
          track: summary(TRACKS.find((t) => t.id === e.track_id)!),
        }));
      return json({ items, next_before: null });
    }

    // --- integrations -----------------------------------------------------------------------
    if (path === "/integrations" && method === "GET")
      return json(this.integrations());
    if (path === "/integrations/listenbrainz/connect" && method === "POST") {
      if (body.token !== this.listenbrainzToken) {
        return route.fulfill({
          status: 422,
          json: {
            detail: {
              message: "ListenBrainz did not accept this token",
              code: "invalid_credentials",
            },
          },
        });
      }
      this.lbConnected = true;
      return json(this.integrations());
    }
    if (path === "/integrations/listenbrainz/import" && method === "POST") {
      if (!body.consent) return error(422, "consent required");
      this.lastImport = {
        id: uuid(8000),
        provider: "listenbrainz",
        status: "completed",
        fetched: 3,
        matched: 2,
        imported: 2,
        duplicates: 0,
        error: null,
        started_at: "2026-11-17T09:00:00Z",
        finished_at: "2026-11-17T09:00:05Z",
      };
      for (const track of TRACKS.slice(0, 2))
        this.events.push({ track_id: track.id, event_type: "play" });
      return json(this.lastImport);
    }
    if (path === "/integrations/listenbrainz" && method === "DELETE") {
      this.lbConnected = false;
      if (url.searchParams.get("delete_imported") === "true") this.events = [];
      return noContent();
    }
    if (path === "/integrations/imports")
      return json(this.lastImport ? [this.lastImport] : []);
    if (path === "/integrations/musicbrainz/search") {
      return json({
        query: url.searchParams.get("q"),
        results: [
          {
            mbid: "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae",
            title: "Not Yet Here",
            artist: "Someone New",
            release: "Debut",
            length_ms: 200000,
            url: "https://musicbrainz.org/recording/8f3471b5-7e6a-48da-86a9-c1c07a0f47ae",
            track_id: null,
          },
        ],
      });
    }
    const exportsMatch = path.match(/^\/playlists\/([0-9a-f-]{36})\/exports?$/);
    if (exportsMatch) {
      const id = exportsMatch[1];
      if (!this.playlists.has(id)) return error(404, "playlist not found");
      if (method === "GET")
        return json({ exports: this.exportsByPlaylist.get(id) ?? [] });
      if (!this.lbConnected || body.provider !== "listenbrainz") {
        return route.fulfill({
          status: 409,
          json: {
            detail: {
              message: "connect listenbrainz first",
              code: "not_connected",
            },
          },
        });
      }
      const record = {
        provider: "listenbrainz",
        status: "completed",
        external_url:
          "https://listenbrainz.org/playlist/7a2c9a5e-0000-4000-8000-000000000001/",
        exported: this.playlists.get(id)!.trackIds.length,
        unmatched: 0,
        attempts: 1,
        error: null,
        updated_at: "2026-11-17T09:00:00Z",
        completed_at: "2026-11-17T09:00:00Z",
      };
      this.exportsByPlaylist.set(id, [record]);
      return json(record);
    }

    // --- playlists --------------------------------------------------------------------------
    if (path === "/playlists" && method === "GET") {
      return json({
        playlists: [...this.playlists.keys()].map((id) =>
          this.playlistSummary(id),
        ),
      });
    }
    if (path === "/playlists" && method === "POST") {
      const id = this.createPlaylist(
        body.name,
        body.track_ids ?? [],
        body.generator ?? null,
      );
      this.playlists.get(id)!.description = body.description ?? null;
      return json(this.playlistDetail(id), 201);
    }
    const playlistMatch = path.match(/^\/playlists\/([0-9a-f-]{36})(\/.*)?$/);
    if (playlistMatch) {
      const [, id, rest = ""] = playlistMatch;
      const playlist = this.playlists.get(id);
      if (!playlist) return error(404, "playlist not found");
      if (rest === "" && method === "GET") return json(this.playlistDetail(id));
      if (rest === "" && method === "PATCH") {
        if (body.name !== undefined) playlist.name = body.name;
        if ("description" in body) playlist.description = body.description;
        return json(this.playlistDetail(id));
      }
      if (rest === "" && method === "DELETE") {
        this.playlists.delete(id);
        return noContent();
      }
      if (rest === "/tracks" && method === "POST") {
        playlist.trackIds = [
          ...new Set([...playlist.trackIds, ...body.track_ids]),
        ];
        return json(this.playlistDetail(id));
      }
      const removeMatch = rest.match(/^\/tracks\/([0-9a-f-]{36})$/);
      if (removeMatch && method === "DELETE") {
        playlist.trackIds = playlist.trackIds.filter(
          (t) => t !== removeMatch[1],
        );
        return json(this.playlistDetail(id));
      }
      if (rest === "/tracks/order" && method === "PUT") {
        playlist.trackIds = body.track_ids;
        return json(this.playlistDetail(id));
      }
      if (rest === "/regenerate" && method === "POST") {
        playlist.trackIds = TRACKS.filter(
          (t) => !playlist.trackIds.includes(t.id),
        ).map((t) => t.id);
        return json(this.playlistDetail(id));
      }
      if (rest === "/suggestions")
        return json(
          response(
            "similar_tracks",
            TRACKS.filter((t) => !playlist.trackIds.includes(t.id)).slice(0, 2),
            "Fits this playlist",
          ),
        );
    }

    this.unhandled.push(`${method} ${path}`);
    return error(404, `mock: no handler for ${method} ${path}`);
  }

  private integrations() {
    const base = { scopes: [], connected_at: "2026-11-17T08:00:00Z" };
    return {
      tokens_configured: true,
      providers: [
        {
          provider: "listenbrainz",
          name: "ListenBrainz",
          description: "Import your listening history and export playlists.",
          auth: "token",
          capabilities: ["export_playlist", "import_history"],
          available: true,
          max_export_tracks: 500,
          connection: this.lbConnected
            ? {
                ...base,
                status: "active",
                external_name: "lb_listener",
                last_import: this.lastImport,
              }
            : null,
        },
        {
          provider: "spotify",
          name: "Spotify",
          description: "Import saved tracks and export playlists.",
          auth: "oauth",
          capabilities: ["export_playlist", "import_history"],
          available: false,
          max_export_tracks: 500,
          connection: null,
        },
        {
          provider: "musicbrainz",
          name: "MusicBrainz",
          description: "Open music encyclopedia.",
          auth: "none",
          capabilities: ["search_tracks"],
          available: true,
          max_export_tracks: 500,
          connection: null,
        },
      ],
    };
  }

  private async profileFor() {
    return {
      user_id: USER_ID,
      profile_version: "taste-profile-test",
      genre_affinity: [],
      artist_affinity: [],
      negative_artists: [],
      listening_frequency: {},
      exploration_preference: 0.4,
      exploration_mode: null,
      discovery_target: 0.5,
      history_size: 1,
      interaction_count: this.events.length,
      last_event_at: null,
    };
  }
}
