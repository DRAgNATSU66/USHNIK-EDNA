// Legislative partner report (t-1027-3): hotspot grid, alerts, flag-rate
// indicators and per-alert chain of custody, all from the recorded API
// fixtures (partner_hotspots, partner_alerts, partner_summary_week,
// report_custody -- services/api/scripts/gen_e2e_fixtures.py).
import { readFileSync } from "node:fs";
import { test, expect, fixture, ANALYSIS_ID } from "./support/mockApi.js";

const PATH = "/partner-report/legislative";
const hotspots = fixture("partner_hotspots");
const alerts = fixture("partner_alerts");
const [cell] = hotspots.cells;
const [alert] = alerts.alerts;

test.describe("legislative partner report", () => {
  test("renders hotspots, alerts and indicators from the API with no mock panels", async ({ page, api }) => {
    await page.goto(PATH);
    await expect(page.getByRole("heading", { name: "eDNA Biodiversity Analyzer" })).toBeVisible();

    // Hotspot grid: one 1-degree cell from the one upload with coordinates.
    await expect(page.getByText("SAMPLING HOTSPOT MAP · 1° GRID")).toBeVisible();
    await expect(page.getByTestId("hotspot-coverage")).toContainText(
      `${hotspots.cells.length} cell(s) from ${hotspots.coverage.uploads_with_coordinates} of ${hotspots.coverage.uploads_in_scope} upload(s) in scope`,
    );
    await expect(page.locator("path.leaflet-interactive")).toHaveCount(hotspots.cells.length);

    // Alerts: from real flags, with the counts the API returned.
    await expect(page.getByText(`ALERTS · ${alerts.total} (${alerts.urgent} URGENT)`)).toBeVisible();
    // Cards render in API order; two analyses share this upload's label, so take the first.
    const card = page.getByRole("button", { name: new RegExp(alert.location_label) }).first();
    await expect(card).toContainText(`${alert.open_urgent_reviews} open urgent review(s)`);
    await expect(card).toContainText(`${alert.contamination_flags} contamination flag(s)`);
    await expect(card).toContainText(`${alert.novelty_flags} novelty flag(s)`);

    // Definitions are the API's own text.
    await page.getByRole("button", { name: "How alerts are defined" }).click();
    await expect(page.getByText(alerts.definitions.priority)).toBeVisible();

    // Indicators: documented flag-rate rule; species list honestly pending.
    await expect(page.getByText("FLAG-RATE INDICATORS")).toBeVisible();
    await expect(page.getByRole("img", { name: "Novelty and contamination flag rate per period" })).toBeVisible();
    await expect(page.getByTestId("indicator-species-pending")).toContainText("Indicator-species list pending");

    // Panels with no data source are gone, and so is every MOCK pill.
    for (const gone of ["MOCK — NO BACKEND YET", "ECONOMIC RISK", "Run Feasibility", "HABITAT-ASSOCIATED", "MarineGenomeDB"]) {
      await expect(page.getByText(gone)).toHaveCount(0);
    }

    expect(api.called("GET /partner/hotspots?cell_deg=1")).toBe(true);
    expect(api.called("GET /partner/alerts?limit=100")).toBe(true);
    expect(api.called("GET /partner/summary?interval=week&top_taxa=1")).toBe(true);
    // A researcher has no scope selector (scope=all is admin/company_owner only).
    await expect(page.getByLabel("Scope")).toHaveCount(0);
  });

  test("a grid cell's popup shows its counts and taxa", async ({ page }) => {
    await page.goto(PATH);
    await page.locator("path.leaflet-interactive").first().click();
    const popup = page.locator(".leaflet-popup-content");
    await expect(popup).toContainText(`Novelty flags: ${cell.novelty_flags} · Contamination flags: ${cell.contamination_flags}`);
    await expect(popup).toContainText(`Distinct taxa: ${cell.distinct_taxa}`);
    await expect(popup).toContainText(cell.top_taxa[0].taxon);
  });

  test("changing the cell size refetches the grid", async ({ page, api }) => {
    await page.goto(PATH);
    await expect(page.getByTestId("hotspot-coverage")).toBeVisible();
    await page.getByLabel("Grid cell size").selectOption("0.5");
    await expect.poll(() => api.called("GET /partner/hotspots?cell_deg=0.5")).toBe(true);
  });

  test("an alert opens its verified chain of custody and exports", async ({ page, api }) => {
    api.override("GET", /^\/reports\/[^/]+\/export\/fair$/, {
      contentType: "application/zip",
      headers: { "content-disposition": `attachment; filename="synthveda_fair_${ANALYSIS_ID}.zip"` },
      body: "PK-e2e",
    });
    await page.goto(PATH);
    await page.getByRole("button", { name: new RegExp(alert.location_label) }).first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(`Analysis ${ANALYSIS_ID}`);
    const custody = fixture("report_custody");
    await expect(dialog).toContainText(`Chain intact — ${custody.verification.length} event(s), every hash recomputed`);
    await expect(dialog).toContainText("Stored results match the hash recorded at completion");
    await expect(dialog).toContainText("Sample metadata unchanged since recorded");
    await expect(dialog).toContainText(custody.file_integrity.reason);
    expect(api.called(`GET /reports/${ANALYSIS_ID}/custody`)).toBe(true);

    const [jsonDl] = await Promise.all([
      page.waitForEvent("download"),
      dialog.getByRole("button", { name: "Download custody JSON" }).click(),
    ]);
    expect(jsonDl.suggestedFilename()).toBe(`synthveda_custody_${ANALYSIS_ID}.json`);
    expect(JSON.parse(readFileSync(await jsonDl.path(), "utf8")).chain_id).toBe(custody.chain_id);

    const [zipDl] = await Promise.all([
      page.waitForEvent("download"),
      dialog.getByRole("button", { name: "Download FAIR ZIP" }).click(),
    ]);
    expect(zipDl.suggestedFilename()).toBe(`synthveda_fair_${ANALYSIS_ID}.zip`);
    expect(api.called(`GET /reports/${ANALYSIS_ID}/export/fair`)).toBe(true);
  });

  test("alerts and cells export as CSV of exactly the returned rows", async ({ page }) => {
    await page.goto(PATH);
    const [alertsDl] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export CSV", exact: true }).click(),
    ]);
    const alertsCsv = readFileSync(await alertsDl.path(), "utf8").trim().split("\n");
    expect(alertsCsv[0].startsWith("analysis_id,upload_id,priority,reasons")).toBe(true);
    expect(alertsCsv).toHaveLength(1 + alerts.alerts.length);
    expect(alertsCsv[1]).toContain(`${ANALYSIS_ID},${alert.upload_id},urgent`);

    const [cellsDl] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export Cells CSV" }).click(),
    ]);
    const cellsCsv = readFileSync(await cellsDl.path(), "utf8").trim().split("\n");
    expect(cellsCsv).toHaveLength(1 + hotspots.cells.length);
    expect(cellsCsv[1].startsWith(`${cell.cell_id},1,${cell.lat_min},${cell.lat_max}`)).toBe(true);
  });

  test("empty scope shows honest empty states and disables exports", async ({ page, api }) => {
    const emptyHotspots = fixture("partner_hotspots");
    emptyHotspots.cells = [];
    emptyHotspots.coverage = { ...emptyHotspots.coverage, uploads_in_scope: 0, uploads_with_coordinates: 0, analyses_in_scope: 0, analyses_mapped: 0 };
    emptyHotspots.notes = ["No uploads in this scope and date range, so there are no cells."];
    const emptyAlerts = fixture("partner_alerts");
    Object.assign(emptyAlerts, { alerts: [], total: 0, urgent: 0, analyses_in_scope: 0,
      notes: ["No analyses in this scope and date range, so there are no alerts."] });
    const emptySummary = fixture("partner_summary_week");
    emptySummary.time_series = [];
    api.override("GET", /^\/partner\/hotspots$/, { body: emptyHotspots });
    api.override("GET", /^\/partner\/alerts$/, { body: emptyAlerts });
    api.override("GET", /^\/partner\/summary$/, { body: emptySummary });

    await page.goto(PATH);
    await expect(page.getByText("No uploads with coordinates in this scope")).toBeVisible();
    await expect(page.getByText(emptyAlerts.notes[0])).toBeVisible();
    await expect(page.getByText("No analysed sequences in this scope yet")).toBeVisible();
    await expect(page.getByRole("button", { name: "Export CSV", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Export Cells CSV" })).toBeDisabled();
  });

  test("an API failure is shown, not hidden", async ({ page, api }) => {
    api.allowConsoleError(/Failed to load resource/);
    api.override("GET", /^\/partner\/alerts$/, { status: 503, body: { detail: "database unavailable" } });
    await page.goto(PATH);
    await expect(page.getByText("Alerts could not be loaded: database unavailable")).toBeVisible();
  });
});

test.describe("legislative partner report (admin)", () => {
  test.use({ role: "admin" });

  test("admin can widen the scope to all users", async ({ page, api }) => {
    await page.goto(PATH);
    await page.getByLabel("Scope").selectOption("all");
    await expect.poll(() => api.called("GET /partner/alerts?scope=all")).toBe(true);
    await expect.poll(() => api.called("GET /partner/hotspots?scope=all")).toBe(true);
    await expect(page.getByText("scope: all users' uploads")).toBeVisible();
  });
});
