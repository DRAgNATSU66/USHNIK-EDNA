// Route guards and redirects from src/main.jsx / ProtectedRoute.jsx.
import { test, expect, ANALYSIS_ID } from "./support/mockApi.js";

test.describe("signed out", () => {
  test.use({ role: null });

  for (const path of ["/upload", "/models", "/reviews", "/admin", `/analysis/${ANALYSIS_ID}`]) {
    test(`${path} sends you to sign in`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/$/);
      await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    });
  }

  test("unknown path falls back to sign in", async ({ page }) => {
    await page.goto("/definitely-not-a-page");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  });
});

test.describe("researcher", () => {
  for (const path of ["/reviews", "/admin"]) {
    test(`${path} is refused and lands on upload`, async ({ page }) => {
      await page.goto(path);
      await expect(page).toHaveURL(/\/upload$/);
      await expect(page.getByRole("heading", { name: "New Analysis" })).toBeVisible();
    });
  }

  test("an already signed-in user on /login goes to upload", async ({ page }) => {
    await page.goto("/login");
    await expect(page).toHaveURL(/\/upload$/);
  });

  for (const [from, to] of [["/home", /\/upload$/], ["/analytics", /\/upload$/], ["/dashboard", /\/upload$/]]) {
    // /home -> / -> (signed in) /upload via Login's redirect.
    test(`${from} redirects`, async ({ page }) => {
      await page.goto(from);
      await expect(page).toHaveURL(to);
    });
  }

  test("bare /researcher-mode keeps ?analysis_id= on its redirect", async ({ page, api }) => {
    await page.goto(`/researcher-mode/unknown-section?analysis_id=${ANALYSIS_ID}`);
    await expect(page).toHaveURL(new RegExp(`/researcher-mode/novelty-dna\\?analysis_id=${ANALYSIS_ID}$`));
    await expect(page.getByRole("heading", { name: "Novelty DNA" })).toBeVisible();
    expect(api.called(`GET /reports/${ANALYSIS_ID}/summary`)).toBe(true);
  });

  test("an expired token is cleared and you are sent to sign in", async ({ page, api }) => {
    api.override("GET", /^\/auth\/me$/, { status: 401, body: { detail: "Token expired" } });
    api.allowConsoleError(/status of 401/);
    await page.goto("/upload");
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("sv_access_token"))).toBeNull();
  });
});

test.describe("curator", () => {
  test.use({ role: "curator" });

  test("/admin is refused for a curator", async ({ page }) => {
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/upload$/);
  });
});
