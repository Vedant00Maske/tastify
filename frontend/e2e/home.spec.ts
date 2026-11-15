import { expect, test } from "@playwright/test";

test("home page shows the TASTIFY heading", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle(/TASTIFY/);
  await expect(
    page.getByRole("heading", { level: 1, name: "TASTIFY" }),
  ).toBeVisible();
});
