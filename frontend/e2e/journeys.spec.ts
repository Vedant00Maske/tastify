import { expect, test as base } from "@playwright/test";

import { MockApi, RESET_TOKEN, TRACKS, VERIFY_TOKEN } from "./support/mock-api";

/**
 * Critical user journeys (Milestone 4): register, onboard, sign in and out, the dashboard,
 * discovery, feedback, playlists and the taste page, against the in-memory API in
 * support/mock-api.ts.
 */
const test = base.extend<{ api: MockApi }>({
  api: async ({ context, page }, provide) => {
    const api = new MockApi(context);
    await api.install(page);
    await provide(api);
    expect(api.unhandled, "requests without a mock handler").toEqual([]);
  },
});

test("signed-out visitors are sent to sign in, and come back afterwards", async ({
  page,
  api,
}) => {
  await page.goto("/taste");
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveURL(/\/login\?next=%2Ftaste$/);

  await page.getByLabel("E-mail").fill(api.email);
  await page.getByLabel("Password").fill("wrong password!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "password" }),
  ).toHaveText("invalid e-mail or password");

  await page.getByLabel("Password").fill(api.password);
  api.onboarded = true;
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/taste$/);
  await expect(
    page.getByRole("heading", { name: "Your taste", exact: true }),
  ).toBeVisible();
});

test("register, onboard and land on a personalized home", async ({
  page,
  api,
}) => {
  await page.goto("/register");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Accept the terms to continue")).toBeVisible();

  await page.getByLabel("Name (optional)").fill("Sam");
  await page.getByLabel("E-mail").fill("sam@example.com");
  await page
    .getByLabel("Password", { exact: true })
    .fill("a long enough password");
  await page.getByLabel("Confirm password").fill("a long enough password");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/onboarding$/);
  await page.waitForLoadState("networkidle");
  await expect(
    page.getByRole("heading", { name: /find your sound/ }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Get started" }).click();

  await page.getByRole("button", { name: "Indie", exact: true }).click();
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Search artists").fill("radio");
  await page.getByRole("button", { name: /Radiohead/ }).click();
  await expect(page.getByLabel("Selected artists")).toContainText("Radiohead");
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByRole("button", { name: "Midnight Drive" }).click();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(
    page.getByRole("slider", { name: "Familiarity versus exploration" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Build my mix" }).click();

  // The first mix is shown only once the API has answered.
  await expect(
    page.getByRole("list", { name: "Your first recommendations" }),
  ).toBeVisible();
  expect(api.preferences.preferred_genres).toEqual(["indie rock"]);
  expect(api.preferences.preferred_moods).toEqual(["midnight-drive"]);
  expect(api.preferences.preferred_artists.map((a) => a.name)).toEqual([
    "Radiohead",
  ]);

  await page.getByRole("button", { name: "Go to my home" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { name: /, Sam$/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your mix" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Made for your mood" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Because you listened to Creep" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Hidden gems" }),
  ).toBeVisible();
});

test("not-yet-onboarded users are sent to onboarding", async ({
  page,
  api,
}) => {
  await api.signIn({ onboarded: false });
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.waitForLoadState("networkidle");
});

test("like, dislike and save from the dashboard, and play without fake audio", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  const grid = page.getByRole("list", { name: "Recommended for you" });
  const first = TRACKS[0].title;

  await grid
    .getByRole("button", { name: `Like ${first}`, exact: true })
    .click();
  await expect(
    grid.getByRole("button", { name: `Unlike ${first}`, exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await grid
    .getByRole("button", { name: `Dislike ${TRACKS[1].title}`, exact: true })
    .click();
  await grid
    .getByRole("button", { name: `Save ${TRACKS[2].title}`, exact: true })
    .click();
  await expect
    .poll(() => api.events.map((e) => e.event_type))
    .toEqual(["like", "dislike", "save"]);

  await page.getByRole("button", { name: "Play mix" }).click();
  const player = page.getByRole("region", { name: "Player" });
  await expect(player).toContainText(first);
  await expect(player.getByRole("link", { name: "YouTube" })).toBeVisible();
  // The player never pretends to play: no playback events are recorded.
  expect(
    api.events.some((e) => ["play", "skip", "complete"].includes(e.event_type)),
  ).toBe(false);
});

test("discover by genre, surprise me and mood mixes", async ({ page, api }) => {
  await api.signIn();
  await page.goto("/discover");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("heading", { name: "Trending" })).toBeVisible();

  await page.getByRole("link", { name: /alternative rock/i }).click();
  await expect(page).toHaveURL(/genre=alternative/);
  await expect(
    page.getByRole("heading", { name: "Top in alternative rock" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "Surprise me" }).click();
  await expect(page.getByRole("list", { name: "Your surprise" })).toContainText(
    TRACKS[4].title,
  );

  await page.goto("/moods/midnight-drive");

  await page.waitForLoadState("networkidle");
  await expect(
    page.getByRole("heading", { name: "Midnight Drive" }),
  ).toBeVisible();
  const mix = page.getByRole("list", { name: "Midnight Drive mix" });
  await expect(mix).toContainText(TRACKS[0].title);
  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(mix).not.toContainText(TRACKS[0].title);
  await page.getByRole("button", { name: "Save as playlist" }).click();
  await expect
    .poll(() => [...api.playlists.values()].map((p) => p.name))
    .toEqual(["Midnight Drive"]);
});

test("create, edit, reorder-free modify and delete a playlist", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/playlists");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("No playlists yet")).toBeVisible();

  await page.getByRole("button", { name: "New playlist" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New playlist" });
  await dialog.getByLabel("Name", { exact: true }).fill("Late night");
  await dialog.getByRole("button", { name: /For you/ }).click();
  await dialog.getByRole("button", { name: "Create" }).click();

  await expect(page).toHaveURL(/\/playlists\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Late night" })).toBeVisible();
  const tracks = page.getByRole("list", { name: "Tracks in Late night" });
  await expect(tracks.getByRole("listitem")).toHaveCount(4);

  await tracks
    .getByRole("button", { name: `Remove ${TRACKS[0].title} from playlist` })
    .click();
  await expect(tracks.getByRole("listitem")).toHaveCount(3);

  await page
    .getByRole("list", { name: "Suggested tracks" })
    .getByRole("button", { name: "Add" })
    .first()
    .click();
  await expect(tracks.getByRole("listitem")).toHaveCount(4);

  await page.getByRole("button", { name: "More playlist actions" }).click();
  await page.getByRole("menuitem", { name: "Edit details" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Name", { exact: true })
    .fill("After hours");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(
    page.getByRole("heading", { name: "After hours" }),
  ).toBeVisible();

  await page.getByRole("button", { name: "More playlist actions" }).click();
  await page.getByRole("menuitem", { name: "Delete playlist" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Delete" })
    .click();
  await expect(page).toHaveURL(/\/playlists$/);
  expect(api.playlists.size).toBe(0);
});

test("taste analytics come with text and a table view", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/taste");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/centres on alternative rock/)).toBeVisible();
  await expect(
    page.getByRole("list", { name: "Genre affinity" }),
  ).toContainText("alternative rock");
  await page.getByRole("button", { name: "Show table" }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "How your taste is changing" }),
  ).toBeVisible();
});

test("search finds tracks and artists and remembers the term", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/search");
  await page.waitForLoadState("networkidle");
  await page
    .getByLabel("Search tracks and artists", { exact: true })
    .last()
    .fill("ween");
  await expect(page).toHaveURL(/q=ween/);
  await expect(page.getByRole("link", { name: "Ocean Man" })).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(
    page.getByRole("button", { name: "ween", exact: true }),
  ).toBeVisible();
});

test("log out ends the session", async ({ page, api }) => {
  await api.signIn();
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("menuitem", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(api.signedIn).toBe(false);
  await page.goto("/home");
  await page.waitForLoadState("networkidle");
  await expect(page).toHaveURL(/\/login\?next=%2Fhome$/);
});

test("reorder a playlist with the keyboard", async ({ page, api }) => {
  await api.signIn();
  const id = api.createPlaylist(
    "Order",
    TRACKS.slice(0, 3).map((t) => t.id),
  );
  await page.goto(`/playlists/${id}`);
  await page.waitForLoadState("networkidle");

  const handle = page.getByRole("button", {
    name: new RegExp(`^Move ${TRACKS[0].title}\.`),
  });
  await handle.focus();
  // dnd-kit measures between steps: give each key a moment, as a person would.
  await page.keyboard.press("Space");
  await page.waitForTimeout(150);
  await page.keyboard.press("ArrowDown");
  await page.waitForTimeout(300);
  await page.keyboard.press("Space");

  await expect
    .poll(() => api.playlists.get(id)?.trackIds)
    .toEqual([TRACKS[1].id, TRACKS[0].id, TRACKS[2].id]);
  const rows = page
    .getByRole("list", { name: "Tracks in Order" })
    .getByRole("listitem");
  await expect(rows.first()).toContainText(TRACKS[1].title);
});

test("change music preferences in settings", async ({ page, api }) => {
  await api.signIn();
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");

  const moods = page.getByRole("group", { name: "Favourite moods" });
  await moods.getByRole("button", { name: "Deep Focus" }).click();
  await expect
    .poll(() => api.preferences.preferred_moods)
    .toEqual(["deep-focus"]);
  await expect(
    moods.getByRole("button", { name: "Deep Focus" }),
  ).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: /Let SONIQUEO learn it/ }).click();
  await expect.poll(() => api.preferences.exploration_mode).toBeNull();

  await page
    .getByRole("switch", { name: "Personalized recommendations" })
    .click();
  await expect.poll(() => api.preferences.personalization_enabled).toBe(false);
});

test("delete the account after confirming the password", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "Delete my account" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await dialog.getByLabel("Confirm with your password").fill("not my password");
  await dialog.getByRole("button", { name: "Delete forever" }).click();
  await expect(dialog.getByRole("alert")).toHaveText("password is wrong");
  expect(api.deleted).toBe(false);

  await dialog.getByLabel("Confirm with your password").fill(api.password);
  await dialog.getByRole("button", { name: "Delete forever" }).click();
  await expect(page).toHaveURL(/\/register$/);
  expect(api.deleted).toBe(true);
});

test("going offline is announced and feedback is sent on reconnect", async ({
  page,
  context,
  api,
}) => {
  await api.signIn();
  await page.goto("/home");
  await page.waitForLoadState("networkidle");

  await context.setOffline(true);
  await expect(page.getByText("You are offline.")).toBeVisible();
  const grid = page.getByRole("list", { name: "Recommended for you" });
  await grid
    .getByRole("button", { name: `Save ${TRACKS[0].title}`, exact: true })
    .click();
  expect(api.events).toEqual([]);

  await context.setOffline(false);
  await expect(page.getByText("You are offline.")).toBeHidden();
  await expect
    .poll(() => api.events.map((e) => e.event_type))
    .toEqual(["save"]);
});

test("connect ListenBrainz, import history and export a playlist", async ({
  page,
  api,
}) => {
  await api.signIn();
  const id = api.createPlaylist(
    "Export me",
    TRACKS.slice(0, 2).map((t) => t.id),
  );
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");

  const services = page.getByRole("list", { name: "Music services" });
  await services.getByLabel("ListenBrainz user token").fill("wrong-token-123");
  await services.getByRole("button", { name: "Connect" }).click();
  await expect(
    services.getByText("ListenBrainz did not accept this token"),
  ).toBeVisible();

  await services
    .getByLabel("ListenBrainz user token")
    .fill(api.listenbrainzToken);
  await services.getByRole("button", { name: "Connect" }).click();
  await expect(services.getByText("Connected", { exact: true })).toBeVisible();

  await services
    .getByRole("button", { name: "Import listening history" })
    .click();
  const consent = page.getByRole("dialog", {
    name: "Import from ListenBrainz?",
  });
  await consent.getByRole("button", { name: "I agree, import" }).click();
  await expect(
    services.getByText(/2 new, 1 not in the catalogue/),
  ).toBeVisible();
  expect(api.events.map((e) => e.event_type)).toEqual(["play", "play"]);

  await page.goto(`/playlists/${id}`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Export" }).click();
  await page.getByRole("menuitem", { name: "ListenBrainz" }).click();
  const exports = page.getByRole("list", { name: "Exports" });
  await expect(exports).toContainText("2 tracks");
  await expect(exports.getByRole("link", { name: /Open/ })).toHaveAttribute(
    "href",
    /listenbrainz\.org\/playlist\//,
  );
});

test("search falls back to MusicBrainz on request", async ({ page, api }) => {
  await api.signIn();
  await page.goto("/search?q=someone");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Search MusicBrainz" }).click();
  const results = page.getByRole("list", { name: "MusicBrainz recordings" });
  await expect(results).toContainText("Not Yet Here");
  await expect(
    results.getByRole("link", { name: /MusicBrainz/ }),
  ).toHaveAttribute("href", /musicbrainz\.org\/recording\//);
});

test("create a playlist from a prompt, regenerate it and save it", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/create");
  await page.waitForLoadState("networkidle");

  const prompt = page.getByLabel("Describe your playlist");
  await prompt.fill("glorbic noise");
  await page.getByRole("button", { name: "Create playlist" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Not recognised" }),
  ).toContainText("Not recognised: glorbic");

  await page
    .getByRole("button", { name: "Something like Radiohead but more upbeat" })
    .click();
  await expect(prompt).toHaveValue("Something like Radiohead but more upbeat");
  await page.getByRole("button", { name: "New to me" }).click();
  await page.getByRole("button", { name: "Create playlist" }).click();

  const understood = page.getByRole("region", {
    name: "What SONIQUEO understood",
  });
  await expect(understood).toContainText("alternative rock");
  await expect(
    understood.getByRole("link", { name: "like Radiohead" }),
  ).toBeVisible();
  await expect(understood).toContainText("no metal");
  await expect(understood).toContainText("Not used: vibes");
  const list = page.getByRole("list", { name: /Playlist for/ });
  await expect(list).toContainText(TRACKS[0].title);
  expect(api.customPrompts[0]).toMatchObject({
    exploration_level: 0.8,
    exclude_previously_heard: true,
  });

  await page.getByRole("button", { name: "Regenerate" }).click();
  await expect(list).not.toContainText(TRACKS[0].title);
  expect((api.customPrompts[1].exclude as string[]).length).toBe(3);

  await page.getByRole("button", { name: "Save as playlist" }).click();
  await expect
    .poll(() => [...api.playlists.values()].map((p) => p.collection))
    .toEqual(["custom"]);
});

// --- Milestone 7: account recovery, verification, legal pages, safe redirects -----------------

test("forgot password: e-mailed link, new password, sign in", async ({
  page,
  api,
}) => {
  api.onboarded = true;
  await page.goto("/login");
  await page.getByRole("link", { name: "Forgot password?" }).click();
  await expect(
    page.getByRole("heading", { name: "Forgot your password?" }),
  ).toBeVisible();
  await page.getByLabel("E-mail").fill(api.email);
  await page.getByRole("button", { name: "Send reset link" }).click();
  await expect(
    page.getByRole("heading", { name: "Check your inbox" }),
  ).toBeVisible();
  expect(api.mail).toEqual([{ kind: "password_reset", to: api.email }]);

  await page.goto(`/reset-password?token=${RESET_TOKEN}`);
  // The token leaves the address bar as soon as the page has read it.
  await expect(page).toHaveURL(/\/reset-password$/);
  await page
    .getByLabel("New password", { exact: true })
    .fill("a fresh passphrase");
  await page.getByLabel("Confirm new password").fill("a fresh passphrase");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(
    page.getByRole("heading", { name: "Password changed" }),
  ).toBeVisible();
  expect(api.password).toBe("a fresh passphrase");

  await page.getByRole("link", { name: "Sign in" }).click();
  await page.getByLabel("E-mail").fill(api.email);
  await page.getByLabel("Password").fill("a fresh passphrase");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);

  // The link works once.
  await page.goto(`/reset-password?token=${RESET_TOKEN}`);
  await page
    .getByLabel("New password", { exact: true })
    .fill("another passphrase");
  await page.getByLabel("Confirm new password").fill("another passphrase");
  await page.getByRole("button", { name: "Set new password" }).click();
  await expect(
    page.getByRole("heading", { name: "This link no longer works" }),
  ).toBeVisible();
});

test("confirm the e-mail address, and ask for a new link from settings", async ({
  page,
  api,
}) => {
  await api.signIn();
  await page.goto("/settings");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText("Address not confirmed yet.")).toBeVisible();
  await page.getByRole("button", { name: "Send confirmation link" }).click();
  await expect(page.getByRole("button", { name: "Link sent" })).toBeDisabled();
  expect(api.mail).toEqual([{ kind: "email_verification", to: api.email }]);

  await page.goto(`/verify-email?token=${VERIFY_TOKEN}`);
  await expect(
    page.getByRole("heading", { name: "E-mail address confirmed" }),
  ).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByText(/Address\s+confirmed/)).toBeVisible();

  await page.goto("/verify-email?token=not-a-valid-token-000000");
  await expect(
    page.getByRole("heading", { name: "This link no longer works" }),
  ).toBeVisible();
});

test("privacy notice and terms are public and linked from registration", async ({
  page,
}) => {
  await page.goto("/register");
  const privacy = page.getByRole("link", { name: "privacy notice" });
  await expect(privacy).toHaveAttribute("href", "/privacy");
  await page.goto("/privacy");
  await expect(
    page.getByRole("heading", { name: "Privacy notice", level: 1 }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Your choices" }),
  ).toBeVisible();
  await page
    .getByRole("navigation", { name: "Legal" })
    .getByRole("link", { name: "Terms" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Terms of use", level: 1 }),
  ).toBeVisible();
});

test("sign-in never redirects to another site", async ({ page, api }) => {
  api.onboarded = true;
  // A backslash: browsers read "/\evil.example" as "//evil.example", another site.
  await page.goto(`/login?next=${encodeURIComponent("/\\evil.example")}`);
  await page.getByLabel("E-mail").fill(api.email);
  await page.getByLabel("Password").fill(api.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/home$/);
  expect(new URL(page.url()).hostname).not.toContain("evil");
});
