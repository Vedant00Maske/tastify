import { expect, test as base } from "@playwright/test";

import { MockApi } from "./support/mock-api";

/**
 * Responsive layout at the specification's breakpoints (mobile < 640, tablet 640–1023,
 * desktop ≥ 1024, wide ≥ 1440): no page may scroll sideways. Screenshots are kept in
 * test-results/ for review.
 */
const test = base.extend<{ api: MockApi }>({
  api: async ({ context, page }, provide) => {
    const api = new MockApi(context);
    await api.install(page);
    await provide(api);
  },
});

const PAGES = [
  "/home",
  "/discover",
  "/moods/midnight-drive",
  "/playlists",
  "/taste",
  "/search?q=ween",
  "/create",
  "/settings",
  "/privacy",
];

for (const width of [360, 768, 1024, 1920]) {
  test(`no horizontal scrolling at ${width}px`, async ({
    page,
    api,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await api.signIn();
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(() => {
        const main = document.getElementById("main");
        return {
          page: document.documentElement.scrollWidth - window.innerWidth,
          main: main ? main.scrollWidth - main.clientWidth : 0,
        };
      });
      expect(overflow, `${path} at ${width}px`).toEqual({ page: 0, main: 0 });
      await page.screenshot({
        path: testInfo.outputPath(
          `${width}-${path.replace(/[^a-z]+/g, "-")}.png`,
        ),
        fullPage: true,
      });
    }
  });
}
