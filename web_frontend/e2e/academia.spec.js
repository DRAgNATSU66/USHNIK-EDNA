// Academia partner page (t-1027-1, M3): every panel reads a recorded API
// response -- environment context, coverage, co-occurrence, rhythms -- and
// the FAIR ZIP button downloads what /reports/{id}/export/fair returns.
import { test, expect, fixture, ANALYSIS_ID } from "./support/mockApi.js";

const PATH = "/partner-report/academia";
const HEADING = "Marine Environment & Bio-Activity Dashboard";
const report = fixture("report");
const UPLOAD_ID = report.metadata.upload_id;
// An empty ZIP archive (end-of-central-directory record only), 22 bytes.
const EMPTY_ZIP = Buffer.from("504b0506" + "00".repeat(18), "hex");

async function open(page) {
  await page.goto(PATH);
  await expect(page.getByRole("heading", { name: HEADING })).toBeVisible();
}

test.describe("academia", () => {
  test("reads every panel from the API and shows no mock tags", async ({ page, api }) => {
    await open(page);

    // Environment: the e2e server has lookups disabled, so the API says pending + why.
    const envCard = page.getByTestId("env-context");
    const env = fixture("environment_context");
    await expect(envCard.getByText("PENDING", { exact: true })).toBeVisible();
    await expect(envCard.getByText(env.reason)).toBeVisible();
    // The upload's own temperature is shown as user-entered.
    const temp = page.getByTestId("env-temperature");
    await expect(temp.getByText("USER-ENTERED")).toBeVisible();
    await expect(temp.getByText(env.variables.temperature.value.toFixed(2))).toBeVisible();

    // Coverage across the user's uploads, from /partner/summary.
    const cov = fixture("partner_summary").environment;
    await expect(page.getByTestId("env-coverage")).toContainText(
      `${cov.eligible} of ${cov.uploads_in_scope} uploads have coordinates and a collection date`);

    // Rhythms: which timestamp each sample was placed by.
    const rt = fixture("partner_rhythms").totals;
    await expect(page.getByTestId("rhythms-basis")).toContainText(
      `${rt.uploads} samples: ${rt.uploads_collected_at} timed by collected_at`);
    await expect(page.getByTestId("rhythms-basis")).toContainText(`${rt.uploads_upload_time} by upload time`);

    // Co-occurrence at species rank: every returned pair is a table row.
    const cooc = fixture("partner_cooccurrence");
    const panel = page.getByTestId("cooccurrence");
    await expect(page.getByTestId("cooccurrence-basis")).toContainText("rank species");
    await expect(panel.locator("tbody tr")).toHaveCount(cooc.pairs.length);
    const first = panel.locator("tbody tr").first();
    await expect(first).toContainText(cooc.pairs[0].taxon_a);
    await expect(first).toContainText(cooc.pairs[0].taxon_b);
    for (const note of cooc.notes) await expect(panel.getByText(note)).toBeVisible();

    await expect(page.getByText(/MOCK/)).toHaveCount(0);
    expect(api.called(`GET /environment/uploads/${UPLOAD_ID}`)).toBe(true);
    expect(api.called("GET /partner/summary?scope=mine")).toBe(true);
    expect(api.called("GET /partner/rhythms?scope=mine")).toBe(true);
    expect(api.called("GET /partner/cooccurrence?scope=mine&rank=species&limit=50")).toBe(true);
    expect(api.called("GET /partner/summary?scope=all")).toBe(false);
  });

  test("co-occurrence rank switch refetches at that rank", async ({ page, api }) => {
    await open(page);
    const panel = page.getByTestId("cooccurrence");
    await panel.getByLabel("Taxonomic rank").selectOption("any");
    const any = fixture("partner_cooccurrence_any");
    await expect(panel.locator("tbody tr")).toHaveCount(any.pairs.length);
    await expect(page.getByTestId("cooccurrence-basis")).toContainText("any recorded rank");
    await expect(panel.locator("tbody").getByText("Myctophum punctatum").first()).toBeVisible();
    expect(api.called("GET /partner/cooccurrence?scope=mine&rank=any&limit=50")).toBe(true);
  });

  test("rhythm charts switch between samples and detections", async ({ page }) => {
    await open(page);
    const panel = page.getByTestId("rhythms");
    const hour = fixture("partner_rhythms").by_hour.find((b) => b.detections > 0);
    await expect(panel.locator("title").filter({ hasText: `${hour.label} UTC: ${hour.uploads} upload` })).toHaveCount(1);
    await panel.getByRole("button", { name: "Detections" }).click();
    await expect(panel.getByRole("button", { name: "Detections" })).toHaveAttribute("aria-pressed", "true");
    await expect(panel.locator("title").filter({ hasText: `${hour.label} UTC: ${hour.detections} detections` })).toHaveCount(1);
  });

  test("a completed lookup shows each variable with its source", async ({ page, api }) => {
    api.override("GET", /^\/environment\/uploads\/[^/]+$/, () => "environment_context_bay");
    await open(page);
    const env = fixture("environment_context_bay");
    await expect(page.getByTestId("env-context").getByText("COMPLETE", { exact: true })).toBeVisible();
    await expect(page.getByText("PUBLIC MODEL")).toHaveCount(6);
    const temp = page.getByTestId("env-temperature");
    await expect(temp.getByText(env.variables.temperature.value.toFixed(2))).toBeVisible();
    await expect(temp.getByText(env.variables.temperature.public.dataset_id, { exact: false })).toBeVisible();
    const wind = page.getByTestId("env-wind");
    await expect(wind.getByText(env.variables.wind.public.source, { exact: false })).toBeVisible();
    await expect(wind.getByText(`DAILY MEAN, ${env.variables.wind.public.series.length} DAYS`, { exact: false })).toBeVisible();
    for (const src of env.sources) {
      await expect(page.getByTestId("env-context").getByText(src.source, { exact: true })).toBeVisible();
    }
  });

  test("an upload without coordinates or date explains why there is no context", async ({ page, api }) => {
    api.override("GET", /^\/environment\/uploads\/[^/]+$/, () => "environment_not_applicable");
    await open(page);
    const env = fixture("environment_not_applicable");
    await expect(page.getByTestId("env-context").getByText("NOT APPLICABLE", { exact: true })).toBeVisible();
    await expect(page.getByText(env.reason)).toBeVisible();
    await expect(page.getByTestId("env-temperature")).toHaveCount(0);
  });

  test("FAIR ZIP button downloads the file the API returns", async ({ page, api }) => {
    const filename = `synthveda_fair_${ANALYSIS_ID}_20261016_090000.zip`;
    api.override("GET", /^\/reports\/[^/]+\/export\/fair$/, {
      contentType: "application/zip",
      headers: { "content-disposition": `attachment; filename="${filename}"` },
      body: EMPTY_ZIP,
    });
    await open(page);
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "⬇ FAIR ZIP" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe(filename);
    await expect(page.getByRole("status")).toHaveText(`Downloaded ${filename} (${EMPTY_ZIP.length} bytes).`);
    expect(api.called(`GET /reports/${ANALYSIS_ID}/export/fair`)).toBe(true);
  });

  test("a refused FAIR export shows the API's reason", async ({ page, api }) => {
    const detail = "Chain of custody is temporarily unavailable. Retry shortly.";
    api.override("GET", /^\/reports\/[^/]+\/export\/fair$/, { status: 503, body: { detail } });
    api.allowConsoleError(/status of 503/);
    await open(page);
    await page.getByRole("button", { name: "⬇ FAIR ZIP" }).click();
    await expect(page.getByRole("alert").filter({ hasText: detail })).toHaveText(`Export failed: ${detail}`);
  });

  test("a failing aggregate leaves the rest of the page working", async ({ page, api }) => {
    api.override("GET", /^\/partner\/cooccurrence$/, { status: 500, body: { detail: "boom" } });
    api.allowConsoleError(/status of 500/);
    await open(page);
    await expect(page.getByTestId("cooccurrence").getByRole("alert")).toHaveText("boom");
    await expect(page.getByTestId("rhythms-basis")).toBeVisible();
  });
});

test.describe("academia as admin", () => {
  test.use({ role: "admin" });

  test("admin can widen the scope to all users", async ({ page, api }) => {
    await open(page);
    await page.getByRole("button", { name: "All users" }).click();
    await expect(page.getByRole("button", { name: "All users" })).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => api.called("GET /partner/cooccurrence?scope=all&rank=species&limit=50")).toBe(true);
    expect(api.called("GET /partner/summary?scope=all")).toBe(true);
    expect(api.called("GET /partner/rhythms?scope=all")).toBe(true);
  });
});
