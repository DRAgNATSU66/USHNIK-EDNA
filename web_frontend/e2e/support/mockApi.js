// Network-layer API mock + page health checks shared by every spec.
//
// - Every request to API_ORIGIN is answered from e2e/fixtures/api/*.json
//   (recorded from the real FastAPI app; see services/api/scripts/
//   gen_e2e_fixtures.py). A request with no matching route gets a 501 and
//   fails the test, so a page calling an endpoint the suite does not know
//   about cannot pass silently.
// - Third-party requests (Google Fonts, the Google Identity script) are
//   answered empty so CI never depends on the internet.
// - Console errors and uncaught page exceptions fail the test.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test as base, expect } from "@playwright/test";

export const API_ORIGIN = "http://api.e2e.invalid";
export const TOKEN = "e2e-not-a-real-jwt";

const FIXTURE_DIR = join(dirname(fileURLToPath(import.meta.url)), "..", "fixtures", "api");
const cache = new Map();

/** Parsed fixture by file stem; a fresh copy each call so tests can mutate it. */
export function fixture(name) {
  if (!cache.has(name)) cache.set(name, readFileSync(join(FIXTURE_DIR, `${name}.json`), "utf8"));
  return JSON.parse(cache.get(name));
}

export const ANALYSIS_ID = fixture("report").metadata.analysis_id;

// [method, pathname regex, (match, url, role) => fixture name | {status, body}]
const ROUTES = [
  ["GET", /^\/health$/, () => "health"],
  ["GET", /^\/auth\/me$/, (_m, _u, role) => `auth_me_${role}`],
  ["GET", /^\/reports$/, () => "reports_list"],
  ["GET", /^\/reports\/[^/]+$/, () => "report"],
  ["GET", /^\/reports\/[^/]+\/summary$/, () => "report_summary"],
  ["GET", /^\/reports\/[^/]+\/novelty$/, () => "report_novelty"],
  ["GET", /^\/reports\/[^/]+\/contamination$/, () => "report_contamination"],
  ["GET", /^\/reviews\/by-sequence$/, () => "reviews_by_sequence"],
  ["GET", /^\/reviews\/stats$/, () => "reviews_stats"],
  ["GET", /^\/reviews\/queue$/, () => "reviews_queue_submitted"],
  ["GET", /^\/field-log\/entries$/, (_m, url) =>
    url.searchParams.get("kind") === "comment" ? "field_entries_comment" : "field_entries_note"],
  ["GET", /^\/field-log\/attachments$/, () => "field_attachments"],
  ["GET", /^\/analysis\/jobs\/job_e2e_complete1$/, () => "job_completed"],
  ["GET", /^\/analysis\/jobs\/[^/]+$/, () => "job_running"],
  ["GET", /^\/models\/registry$/, () => "models_registry"],
  ["GET", /^\/models\/promotions$/, () => "models_promotions"],
  ["GET", /^\/abyss\/expeditions$/, () => "abyss_expeditions"],
  // Academia (t-1027-1)
  ["GET", /^\/environment\/uploads\/upl_e2e0000000002$/, () => "environment_context_bay"],
  ["GET", /^\/environment\/uploads\/upl_e2e0000000003$/, () => "environment_not_applicable"],
  ["GET", /^\/environment\/uploads\/[^/]+$/, () => "environment_context"],
  ["GET", /^\/partner\/summary$/, (_m, url) =>
    url.searchParams.get("interval") === "week" ? "partner_summary_week" : "partner_summary"],
  ["GET", /^\/partner\/cooccurrence$/, (_m, url) =>
    url.searchParams.get("rank") === "any" ? "partner_cooccurrence_any" : "partner_cooccurrence"],
  ["GET", /^\/partner\/rhythms$/, () => "partner_rhythms"],
  // Legislative (t-1027-3)
  ["GET", /^\/partner\/hotspots$/, () => "partner_hotspots"],
  ["GET", /^\/partner\/alerts$/, () => "partner_alerts"],
  ["GET", /^\/reports\/[^/]+\/custody$/, () => "report_custody"],
];

function json(route, status, body) {
  return route.fulfill({
    status,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  });
}

export const test = base.extend({
  // null = signed out; otherwise the role whose /auth/me fixture is served.
  role: ["researcher", { option: true }],

  // Per-test overrides: api.override("GET", /^\/health$/, {status, body}).
  // Also records every API call as "METHOD /path?query".
  api: async ({ context, role }, use) => {
    const calls = [];
    const unmocked = [];
    const overrides = [];
    const allowedErrors = [];

    await context.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.hostname === "127.0.0.1" || url.hostname === "localhost") return route.continue();
        if (url.origin !== API_ORIGIN) {
          // Third-party (fonts, Google Identity script): empty, never online.
          return route.fulfill({ status: 200, body: "" });
        }
        if (req.method() === "OPTIONS") {
          return route.fulfill({
            status: 204,
            headers: {
              "access-control-allow-origin": "*",
              "access-control-allow-headers": "*",
              "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE",
            },
          });
        }
        calls.push(`${req.method()} ${url.pathname}${url.search}`);
        for (const [method, re, handler] of [...overrides, ...ROUTES]) {
          const m = req.method() === method && url.pathname.match(re);
          if (!m) continue;
          const out = typeof handler === "function" ? handler(m, url, role) : handler;
          if (typeof out === "string") return json(route, 200, fixture(out));
          // Non-JSON body (a file download): {status?, contentType, headers?, body}.
          if (out.contentType) {
            return route.fulfill({
              status: out.status ?? 200,
              contentType: out.contentType,
              headers: { "access-control-allow-origin": "*", "access-control-expose-headers": "Content-Disposition", ...out.headers },
              body: out.body,
            });
          }
          return json(route, out.status ?? 200, out.body);
        }
        unmocked.push(`${req.method()} ${url.pathname}`);
        return json(route, 501, { detail: `e2e: no mock for ${req.method()} ${url.pathname}` });
    });

    await use({
      calls,
      override: (method, re, handler) => overrides.unshift([method, re, handler]),
      called: (prefix) => calls.some((c) => c.startsWith(prefix)),
      // For a test that provokes an error on purpose (e.g. a 401, which
      // Chromium logs as "Failed to load resource").
      allowConsoleError: (re) => allowedErrors.push(re),
      allowedErrors,
    });

    expect(unmocked, "API calls with no mock (add a fixture + route)").toEqual([]);
  },

  // Seed the session the app reads on load (AuthContext.jsx): the bearer
  // token and the cached profile. /auth/me is then served for `role`.
  page: async ({ page, role, api }, use) => {
    // Depends on `api` so routes are installed before the first navigation.
    const errors = [];
    page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`);
    });
    if (role) {
      const profile = fixture(`auth_me_${role}`);
      await page.addInitScript(
        ([token, user]) => {
          // Only on first load of the test, so a page that logs out stays out.
          if (sessionStorage.getItem("e2e_seeded")) return;
          sessionStorage.setItem("e2e_seeded", "1");
          localStorage.setItem("sv_access_token", token);
          localStorage.setItem("sv_user_profile", JSON.stringify(user));
        },
        [TOKEN, profile],
      );
    }
    await use(page);
    const unexpected = errors.filter((e) => !api.allowedErrors.some((re) => re.test(e)));
    expect(unexpected, "console errors / uncaught exceptions").toEqual([]);
  },
});

export { expect };
