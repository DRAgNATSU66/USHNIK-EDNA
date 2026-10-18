// Optional smoke run against a real local API (not part of CI):
//   cd services/api && .venv/bin/uvicorn app.main:app --port 8000   # needs Mongo
//   cd web_frontend && E2E_REAL_API=1 npm run test:e2e
// E2E_API_URL overrides the API (default http://127.0.0.1:8000).
// E2E_REAL_TOKEN (a JWT the API accepts) also checks an authenticated page.
// No mocks here: requests go to the real API.
import { test, expect } from "@playwright/test";

const REAL = process.env.E2E_REAL_API === "1";
const API_URL = process.env.E2E_API_URL || "http://127.0.0.1:8000";
const TOKEN = process.env.E2E_REAL_TOKEN;

test.skip(!REAL, "set E2E_REAL_API=1 to run against a real API");

test("API /health answers with the fields the frontend reads", async ({ request }) => {
  const resp = await request.get(`${API_URL}/health`);
  expect(resp.ok()).toBe(true);
  const body = await resp.json();
  expect(body.status).toBe("ok");
  expect(Number.isFinite(body.max_upload_size_mb)).toBe(true);
  expect(Number.isFinite(body.novelty_threshold)).toBe(true);
});

test("login page loads against the real API", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("model registry page loads with a real token", async ({ page, request }) => {
  test.skip(!TOKEN, "set E2E_REAL_TOKEN to check an authenticated page");
  const me = await request.get(`${API_URL}/auth/me`, { headers: { Authorization: `Bearer ${TOKEN}` } });
  expect(me.ok(), "E2E_REAL_TOKEN rejected by /auth/me").toBe(true);
  const profile = await me.json();
  await page.addInitScript(([t, u]) => {
    localStorage.setItem("sv_access_token", t);
    localStorage.setItem("sv_user_profile", JSON.stringify(u));
  }, [TOKEN, profile]);
  await page.goto("/models");
  await expect(page.getByRole("heading", { name: "Model Registry" })).toBeVisible();
  await expect(page.getByText("Loading models...")).toHaveCount(0);
  await expect(page.getByText(/Failed|HTTP \d+/)).toHaveCount(0);
});
