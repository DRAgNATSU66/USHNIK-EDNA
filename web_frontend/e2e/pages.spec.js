// One test per routed page in src/main.jsx. Each one checks the page renders
// its primary heading, that data from the recorded API fixture reaches the
// screen (so the call path is wired, not just the shell), and -- via the
// shared fixture in support/mockApi.js -- that no console error, uncaught
// exception or unmocked API call happened along the way.
import { test, expect, fixture, ANALYSIS_ID } from "./support/mockApi.js";

const report = fixture("report");
const SOURCE_FILE = report.metadata.source_file;

test.describe("public auth pages", () => {
  test.use({ role: null });

  for (const path of ["/", "/login"]) {
    test(`login ${path}`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
      await expect(page.getByRole("heading", { name: /Unravel the intricacies/ })).toBeVisible();
    });
  }

  test("signup", async ({ page }) => {
    await page.goto("/signup");
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
  });

  test("forgot password", async ({ page }) => {
    await page.goto("/forgot-password");
    await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
  });

  test("reset password without a recovery link says it is invalid", async ({ page }) => {
    // Supabase is unconfigured in the e2e build, so there is no recovery
    // context; the page must refuse rather than render the form.
    await page.goto("/reset-password");
    await expect(page.getByRole("heading", { name: "Link invalid or expired" })).toBeVisible();
  });
});

test.describe("researcher pages", () => {
  test("upload reads the size limit from /health", async ({ page, api }) => {
    // A non-default limit, so the text can only come from the API response.
    api.override("GET", /^\/health$/, { body: { ...fixture("health"), max_upload_size_mb: 37 } });
    await page.goto("/upload");
    await expect(page.getByRole("heading", { name: "New Analysis" })).toBeVisible();
    await expect(page.getByText(/up to 37\s*MB/)).toBeVisible();
  });

  test("novelty DNA falls back to the latest analysis and lists its candidates", async ({ page, api }) => {
    await page.goto("/researcher-mode/novelty-dna");
    await expect(page.getByRole("heading", { name: "Novelty DNA" })).toBeVisible();
    await expect(page.getByText(SOURCE_FILE, { exact: false })).toBeVisible();
    for (const entry of fixture("report_novelty").entries) {
      await expect(page.getByText(entry.sequence_id, { exact: true }).first()).toBeVisible();
    }
    // Slider floor comes from /health novelty_threshold.
    await expect(page.getByText(`Server flags at ≥ ${Math.round(fixture("health").novelty_threshold * 100)}%`)).toBeVisible();
    expect(api.called("GET /reports?limit=1")).toBe(true);
    for (const p of ["summary", "novelty", "contamination"]) {
      expect(api.called(`GET /reports/${ANALYSIS_ID}/${p}`)).toBe(true);
    }
  });

  test("species correction lists assignments and opens correction history", async ({ page, api }) => {
    await page.goto(`/researcher-mode/species-correction?analysis_id=${ANALYSIS_ID}`);
    await expect(page.getByRole("heading", { name: "Species Correction" })).toBeVisible();
    await expect(page.getByText(SOURCE_FILE)).toBeVisible();
    const known = report.taxonomic_assignments.find((a) => a.sequence_id === "seq_e2e_lantern_002");
    await expect(page.getByText(known.predicted_taxon).first()).toBeVisible();
    // An explicit ?analysis_id= skips the "latest analysis" lookup.
    expect(api.called("GET /reports?")).toBe(false);

    await page.getByText(known.sequence_id, { exact: true }).first().click();
    const history = fixture("reviews_by_sequence");
    await expect(page.getByText(history[0].proposed_taxon).first()).toBeVisible();
    expect(api.called(`GET /reviews/by-sequence?analysis_id=${ANALYSIS_ID}&sequence_id=${known.sequence_id}`)).toBe(true);
  });

  test("field log shows notes, discussion and attachments", async ({ page, api }) => {
    await page.goto("/researcher-mode/comments");
    await expect(page.getByRole("heading", { name: "Field Log" })).toBeVisible();
    await expect(page.getByText(fixture("field_entries_note")[0].body)).toBeVisible();
    const [rootComment, reply] = fixture("field_entries_comment");
    await expect(page.getByText(reply.body)).toBeVisible();
    await expect(page.getByText(rootComment.author_name).first()).toBeVisible();
    await expect(page.getByText(fixture("field_attachments")[0].original_filename).first()).toBeVisible();
    expect(api.called(`GET /field-log/entries?analysis_id=${ANALYSIS_ID}&kind=note`)).toBe(true);
    expect(api.called(`GET /field-log/entries?analysis_id=${ANALYSIS_ID}&kind=comment`)).toBe(true);
  });

  test("job progress shows a running job", async ({ page }) => {
    const job = fixture("job_running");
    await page.goto(`/jobs/${job.job_id}`);
    await expect(page.getByText(job.job_id)).toBeVisible();
    await expect(page.getByText(job.upload_id)).toBeVisible();
    await expect(page.getByText("Running inference")).toBeVisible();
  });

  test("job progress forwards a completed job to its analysis report", async ({ page }) => {
    const job = fixture("job_completed");
    await page.goto(`/jobs/${job.job_id}`);
    await expect(page).toHaveURL(new RegExp(`/analysis/${job.analysis_id}$`), { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Analysis Report" })).toBeVisible();
  });

  test("analysis report renders the report", async ({ page, api }) => {
    await page.goto(`/analysis/${ANALYSIS_ID}`);
    await expect(page.getByRole("heading", { name: "Analysis Report" })).toBeVisible();
    await expect(page.getByText(SOURCE_FILE).first()).toBeVisible();
    await expect(page.getByText(report.possible_novelty[0].sequence_id).first()).toBeVisible();
    expect(api.called(`GET /reports/${ANALYSIS_ID}`)).toBe(true);
  });

  test("model status lists the registry", async ({ page }) => {
    await page.goto("/models");
    await expect(page.getByRole("heading", { name: "Model Registry" })).toBeVisible();
    for (const m of fixture("models_registry").models) {
      await expect(page.getByRole("heading", { name: m.model_id, exact: true })).toBeVisible();
    }
  });

  test("abyss mode lists expeditions (no create form for a researcher)", async ({ page }) => {
    const [exp] = fixture("abyss_expeditions").expeditions;
    await page.goto("/abyss");
    await expect(page.getByRole("heading", { name: "Abyss Mode" })).toBeVisible();
    await expect(page.getByText(exp.name)).toBeVisible();
    await expect(page.getByText("EXPEDITIONS (1)")).toBeVisible();
    await expect(page.getByText("NEW EXPEDITION")).toHaveCount(0);
  });
});

test.describe("partner reports", () => {
  test("academia renders the latest analysis", async ({ page, api }) => {
    await page.goto("/partner-report/academia");
    await expect(page.getByRole("heading", { name: "Marine Environment & Bio-Activity Dashboard" })).toBeVisible();
    await expect(page.getByText(`Run ${ANALYSIS_ID}`, { exact: false }).first()).toBeVisible();
    expect(api.called("GET /reports?limit=1")).toBe(true);
    expect(api.called(`GET /reports/${ANALYSIS_ID}`)).toBe(true);
  });

  test("legislative", async ({ page }) => {
    await page.goto("/partner-report/legislative");
    await expect(page.getByRole("heading", { name: "eDNA Biodiversity Analyzer" })).toBeVisible();
  });

  test("industrial", async ({ page }) => {
    await page.goto("/partner-report/industrial");
    await expect(page.getByRole("heading", { name: "Enterprise Compliance Dashboard" })).toBeVisible();
  });
});

test.describe("curator pages", () => {
  test.use({ role: "curator" });

  test("review queue shows stats and submitted reviews", async ({ page, api }) => {
    await page.goto("/reviews");
    await expect(page.getByRole("heading", { name: "Review Queue" })).toBeVisible();
    for (const r of fixture("reviews_queue_submitted")) {
      await expect(page.getByText(r.review_type.replace(/_/g, " ")).first()).toBeVisible();
    }
    expect(api.called("GET /reviews/stats")).toBe(true);
    expect(api.called("GET /reviews/queue?state=submitted")).toBe(true);
  });
});

test.describe("admin pages", () => {
  test.use({ role: "admin" });

  test("admin panel shows the registry and promotion history", async ({ page, api }) => {
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Admin Panel" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Model Promotion" })).toBeVisible();
    const [event] = fixture("models_promotions").events;
    await expect(page.getByText(`on ${event.route} by ${event.actor_email}`)).toBeVisible();
    await expect(page.getByText(fixture("models_registry").models[0].model_id).first()).toBeVisible();
    expect(api.called("GET /reviews/stats")).toBe(true);
    expect(api.called("GET /models/promotions?limit=10")).toBe(true);
  });
});
