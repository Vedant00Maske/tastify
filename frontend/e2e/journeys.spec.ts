import { expect, test as base } from "@playwright/test";

import { MockApi, TRACKS } from "./support/mock-api";

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
