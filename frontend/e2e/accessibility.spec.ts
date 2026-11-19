import AxeBuilder from "@axe-core/playwright";
import { expect, test as base, type Page } from "@playwright/test";

import { MockApi } from "./support/mock-api";

/**
 * Automated WCAG 2.1 AA checks (axe-core) on every page, in the dark theme at desktop and phone
 * widths. Automated checks find a subset of problems; keyboard and screen-reader flows are
 * covered by the journeys (journeys.spec.ts).
 */
const test = base.extend<{ api: MockApi }>({
  api: async ({ context, page }, provide) => {
    const api = new MockApi(context);
    await api.install(page);
    await provide(api);
  },
});

async function audit(page: Page) {
  // Let entrance animations finish: half-faded text would be measured at the wrong contrast.
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(600);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")),
  }));
  expect(summary, JSON.stringify(summary, null, 2)).toEqual([]);
}

const SIGNED_OUT = ["/login", "/register"];
const SIGNED_IN = [
  "/home",
  "/discover",
  "/moods",
  "/moods/midnight-drive",
  "/playlists",
  "/taste",
  "/search?q=ween",
  "/create",
  "/settings",
  "/artists/00000000-0000-4000-8000-000000000064",
  "/tracks/00000000-0000-4000-8000-0000000000c8",
];

for (const width of [1440, 390]) {
  test.describe(`at ${width}px`, () => {
    test.use({ viewport: { width, height: 900 } });

    for (const path of SIGNED_OUT) {
      test(`${path} has no WCAG A/AA violations`, async ({ page }) => {
        await page.goto(path);
        await audit(page);
      });
    }

    for (const path of SIGNED_IN) {
      test(`${path} has no WCAG A/AA violations`, async ({ page, api }) => {
        await api.signIn();
        api.createPlaylist("Late night", [], { collection: "for_you" });
        await page.goto(path);
        await audit(page);
      });
    }

    test("a playlist page has no WCAG A/AA violations", async ({
      page,
      api,
    }) => {
      await api.signIn();
      const id = api.createPlaylist("Late night", [], {
        collection: "for_you",
      });
      await page.goto(`/playlists/${id}`);
      await audit(page);
    });

    test("onboarding has no WCAG A/AA violations", async ({ page, api }) => {
      await api.signIn({ onboarded: false });
      await page.goto("/onboarding");
      await audit(page);
      await page.getByRole("button", { name: "Get started" }).click();
      await audit(page);
    });
  });
}
