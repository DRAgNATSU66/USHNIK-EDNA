// Self-checks for the safety nets in support/mockApi.js. Each test does the
// thing the harness must catch and is marked test.fail(), so the suite goes
// red if a net stops catching it (a silent harness would pass every page).
import { test, API_ORIGIN } from "./support/mockApi.js";

test.describe("harness", () => {
  test.use({ role: null });

  test("a console error fails the test", async ({ page }) => {
    test.fail();
    await page.goto("/login");
    await page.evaluate(() => console.error("deliberate"));
  });

  test("an uncaught exception fails the test", async ({ page }) => {
    test.fail();
    await page.goto("/login");
    await page.evaluate(() => setTimeout(() => { throw new Error("deliberate"); }, 0));
    await page.waitForTimeout(100);
  });

  test("an API call with no mock fails the test", async ({ page, api }) => {
    test.fail();
    await page.goto("/login");
    api.allowConsoleError(/status of 501/); // isolate the unmocked-call check
    await page.evaluate((origin) => fetch(`${origin}/not/a/route`).catch(() => {}), API_ORIGIN);
  });
});
