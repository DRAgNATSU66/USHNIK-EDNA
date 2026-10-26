// Integrity sweep (t-1028-3, D6): every model-derived score carries a
// ConfidenceChip, Legislative alerts carry a DetectionWindowBadge, the Novelty
// DNA drawer reads the stored reference lookup instead of a placeholder, CSV
// exports cannot smuggle spreadsheet formulas, and partner panels never show a
// superseded response.
import { readFileSync } from "node:fs";
import { test, expect, fixture, ANALYSIS_ID, ORCH_ANALYSIS_ID, API_ORIGIN } from "./support/mockApi.js";

const NOVELTY_CHIP = "Modeled estimate — based on 6 expert-weighted signals · Confidence: uncalibrated score";
const CONTAMINATION_CHIP = "Modeled estimate — based on route, marker and composition signals · Confidence: uncalibrated score";
const WINDOW = "trace consistent with presence ~1–14 days prior to collection";

// A page-level route wins over the shared context-level mock, so a test can
// hold one response back to reproduce a race.
async function delayed(page, re, ms, body, status = 200) {
  await page.route((url) => url.origin === API_ORIGIN && re.test(url.pathname + url.search), async (route) => {
    await new Promise((r) => setTimeout(r, ms));
    await route.fulfill({
      status,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify(body),
    }).catch(() => {}); // page may already be closed
  });
}

// Client-side navigation (no reload), the way an in-app link changes ?analysis_id=.
async function pushUrl(page, url) {
  await page.evaluate((u) => {
    window.history.pushState({}, "", u);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }, url);
}

test.describe("ConfidenceChip on model-derived scores", () => {
  test("novelty DNA rows and drawer qualify the novelty and contamination scores", async ({ page }) => {
    const entries = fixture("report_novelty").entries;
    await page.goto("/researcher-mode/novelty-dna");
    await expect(page.getByText(entries[0].sequence_id, { exact: true })).toBeVisible();
    await expect(page.getByText(NOVELTY_CHIP)).toHaveCount(entries.length);

    await page.getByText(entries[0].sequence_id, { exact: true }).click();
    await expect(page.getByText("DEEP ALIGNMENT VIEWER")).toBeVisible();
    await expect(page.getByText(CONTAMINATION_CHIP)).toBeVisible();
  });

  test("results novelty preview qualifies each score", async ({ page }) => {
    const report = fixture("report");
    await page.goto(`/analysis/${ANALYSIS_ID}`);
    await expect(page.getByText("POSSIBLE NOVELTY — PREVIEW")).toBeVisible();
    await expect(page.getByText(NOVELTY_CHIP)).toHaveCount(Math.min(3, report.possible_novelty.length));
  });

  test.describe("as curator", () => {
    test.use({ role: "curator" });

    test("review queue qualifies the scores it shows", async ({ page }) => {
      const queue = fixture("reviews_queue_submitted");
      await page.goto("/reviews");
      await expect(page.getByText(queue[0].review_id).first()).toBeVisible();
      await expect(page.getByText(NOVELTY_CHIP)).toHaveCount(queue.filter((r) => r.novelty_score != null).length);
      await expect(page.getByText(CONTAMINATION_CHIP)).toHaveCount(queue.filter((r) => r.contamination_score != null).length);
    });
  });

  test("industrial urgent reviews qualify their scores", async ({ page }) => {
    const urgent = fixture("partner_incidents").urgent_reviews;
    await page.goto("/partner-report/industrial");
    await expect(page.getByTestId("urgent-review").first()).toBeVisible();
    await expect(page.getByTestId("urgent-review").getByText(NOVELTY_CHIP))
      .toHaveCount(urgent.filter((r) => r.novelty_score != null).length);
  });
});

test.describe("novelty DNA reference lookup (stored decision)", () => {
  test("an orchestrated candidate shows its recorded closest match, identity and database", async ({ page, api }) => {
    const analysis = fixture("analysis_orchestrated");
    const tuna = analysis.results.find((r) => r.sequence_id === "seq_e2e_orch_tuna_01");
    const vent = analysis.results.find((r) => r.sequence_id === "seq_e2e_orch_vent_04");
    const novelty = fixture("report_novelty");
    novelty.analysis_id = ORCH_ANALYSIS_ID;
    novelty.entries = [
      { ...novelty.entries[0], sequence_id: tuna.sequence_id },
      { ...novelty.entries[1], sequence_id: vent.sequence_id },
    ];
    api.override("GET", new RegExp(`^/reports/${ORCH_ANALYSIS_ID}/novelty$`), { body: novelty });

    await page.goto(`/researcher-mode/novelty-dna?analysis_id=${ORCH_ANALYSIS_ID}`);
    await page.getByText(tuna.sequence_id, { exact: true }).click();
    const lookup = page.getByTestId("reference-lookup");
    const d = tuna.decision;
    await expect(lookup).toContainText(d.predicted_taxon);
    await expect(lookup).toContainText(`(${d.taxon_rank})`);
    await expect(lookup).toContainText(`${d.percent_identity.toFixed(2)}%`);
    await expect(lookup).toContainText(`${d.reference_db} ${d.reference_db_version}`);
    await expect(lookup).toContainText(`best hit in ${d.reference_db} ${d.reference_db_version} · Confidence: not estimated (single hit)`);
    await expect(page.getByText("aren't available")).toHaveCount(0);

    // A searched sequence with no assignment says exactly that -- no identity.
    await page.getByRole("button", { name: "✕" }).click();
    await page.getByText(vent.sequence_id, { exact: true }).click();
    await expect(lookup).toContainText("searched, no reference assignment");
    await expect(lookup).not.toContainText("IDENTITY");

    // Rows are fetched once per analysis, without traces.
    expect(api.calls.filter((c) => c.startsWith(`GET /analysis/${ORCH_ANALYSIS_ID}`))).toEqual([
      `GET /analysis/${ORCH_ANALYSIS_ID}?include_trace=false`,
    ]);
  });

  test("a pre-orchestrator candidate says no lookup was recorded", async ({ page, api }) => {
    const entry = fixture("report_novelty").entries[0];
    const legacy = fixture("analysis_legacy");
    legacy.analysis_id = ANALYSIS_ID;
    legacy.results = [{ ...legacy.results[0], sequence_id: entry.sequence_id, decision: null }];
    api.override("GET", new RegExp(`^/analysis/${ANALYSIS_ID}$`), { body: legacy });

    await page.goto("/researcher-mode/novelty-dna");
    await page.getByText(entry.sequence_id, { exact: true }).click();
    await expect(page.getByTestId("reference-lookup")).toContainText("No reference lookup recorded for this sequence");
  });

  test("a failed load is said, not hidden", async ({ page, api }) => {
    api.allowConsoleError(/Failed to load resource/);
    api.override("GET", new RegExp(`^/analysis/${ANALYSIS_ID}$`), { status: 503, body: { detail: "database unavailable" } });
    const entry = fixture("report_novelty").entries[0];
    await page.goto("/researcher-mode/novelty-dna");
    await page.getByText(entry.sequence_id, { exact: true }).click();
    await expect(page.getByTestId("reference-lookup")).toContainText("could not be loaded: database unavailable");
  });
});

test.describe("legislative integrity", () => {
  test("alerts carry a detection window from their own collection date", async ({ page, api }) => {
    const alerts = fixture("partner_alerts");
    alerts.alerts[alerts.alerts.length - 1].collected_at = null;
    api.override("GET", /^\/partner\/alerts$/, { body: alerts });
    await page.goto("/partner-report/legislative");
    const windows = page.getByTestId("alert-detection-window");
    await expect(windows).toHaveCount(alerts.alerts.length);
    await expect(windows.first()).toContainText(WINDOW);
    await expect(windows.last()).toContainText("Detection window: unavailable (no sample timestamp)");

    await page.getByRole("button", { name: new RegExp(alerts.alerts[0].location_label) }).first().click();
    await expect(page.getByRole("dialog")).toContainText(WINDOW);
  });

  test("CSV exports neutralise spreadsheet formulas but keep numbers", async ({ page, api }) => {
    const alerts = fixture("partner_alerts");
    Object.assign(alerts.alerts[0], {
      location_label: '=HYPERLINK("http://x.invalid","Station 7")',
      original_filename: "+cmd.fasta",
      latitude: -12.5,
    });
    alerts.alerts[1].location_label = "@SUM(A1)";
    alerts.alerts[2].location_label = "\tTabbed";
    const hotspots = fixture("partner_hotspots");
    Object.assign(hotspots.cells[0], { cell_id: "-13:68", lat_min: -13, lat_max: -12, location_labels: ["-Station"] });
    api.override("GET", /^\/partner\/alerts$/, { body: alerts });
    api.override("GET", /^\/partner\/hotspots$/, { body: hotspots });

    await page.goto("/partner-report/legislative");
    const [alertsDl] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export CSV", exact: true }).click(),
    ]);
    const alertsCsv = readFileSync(await alertsDl.path(), "utf8");
    expect(alertsCsv).toContain(`"'=HYPERLINK(""http://x.invalid"",""Station 7"")"`);
    expect(alertsCsv).toContain(",'+cmd.fasta,");
    expect(alertsCsv).toContain(",'@SUM(A1),");
    expect(alertsCsv).toContain(",'\tTabbed,");
    expect(alertsCsv).toContain(",-12.5,"); // a number is not touched
    expect(alertsCsv).not.toMatch(/,[=+@]/);

    const [cellsDl] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Export Cells CSV" }).click(),
    ]);
    const row = readFileSync(await cellsDl.path(), "utf8").trim().split("\n")[1];
    expect(row.startsWith("'-13:68,1,-13,-12,")).toBe(true);
    expect(row).toContain(",'-Station,");
  });

  test("the custody panel is re-read after a FAIR export", async ({ page, api }) => {
    const before = fixture("report_custody");
    const after = fixture("report_custody");
    after.verification.length = before.verification.length + 1;
    after.verification.head_hash = "f".repeat(64);
    let custodyCalls = 0;
    api.override("GET", /^\/reports\/[^/]+\/custody$/, () => ({ body: ++custodyCalls === 1 ? before : after }));
    api.override("GET", /^\/reports\/[^/]+\/export\/fair$/, {
      contentType: "application/zip",
      headers: { "content-disposition": `attachment; filename="synthveda_fair_${ANALYSIS_ID}.zip"` },
      body: "PK-e2e",
    });
    await page.goto("/partner-report/legislative");
    await page.getByRole("button", { name: new RegExp(fixture("partner_alerts").alerts[0].location_label) }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText(`Chain intact — ${before.verification.length} event(s)`);

    await Promise.all([page.waitForEvent("download"), dialog.getByRole("button", { name: "Download FAIR ZIP" }).click()]);
    await expect(dialog).toContainText(`Chain intact — ${after.verification.length} event(s)`);
    expect(custodyCalls).toBe(2);

    const [jsonDl] = await Promise.all([
      page.waitForEvent("download"),
      dialog.getByRole("button", { name: "Download custody JSON" }).click(),
    ]);
    expect(JSON.parse(readFileSync(await jsonDl.path(), "utf8")).verification.length).toBe(after.verification.length);
  });
});

test.describe("industrial scope switch (admin)", () => {
  test.use({ role: "admin" });

  test("a slow 'My data' response cannot replace the 'All users' one", async ({ page }) => {
    const mine = fixture("partner_incidents");
    mine.incidents = mine.incidents.map((i) => ({ ...i, source_file: "STALE-MINE.fasta" }));
    await delayed(page, /^\/partner\/incidents\?scope=mine$/, 1500, mine);

    await page.goto("/partner-report/industrial");
    await page.getByRole("button", { name: "My data" }).click();
    await page.getByRole("button", { name: "All users" }).click();
    const allFirst = fixture("partner_incidents").incidents[0];
    await expect(page.getByTestId("incident-row").first()).toContainText(allFirst.source_file || allFirst.analysis_id);
    await page.waitForTimeout(1800); // the held 'mine' response lands now
    await expect(page.getByText("STALE-MINE.fasta")).toHaveCount(0);
  });
});

test.describe("academia integrity", () => {
  const OTHER = "ana_e2e_other_upload";

  function otherReport() {
    const r = fixture("report");
    r.metadata = { ...r.metadata, analysis_id: OTHER, upload_id: "upl_e2e0000000002" };
    return r;
  }

  test("a superseded environment response is ignored", async ({ page, api }) => {
    api.override("GET", new RegExp(`^/reports/${OTHER}$`), { body: otherReport() });
    // The first upload's context is held back and arrives after the second's.
    await delayed(page, /^\/environment\/uploads\/upl_e2e0000000001$/, 1500, fixture("environment_context"));

    await page.goto(`/partner-report/academia?analysis_id=${ANALYSIS_ID}`);
    await expect(page.getByTestId("env-context")).toContainText("Loading environmental context");
    await pushUrl(page, `/partner-report/academia?analysis_id=${OTHER}`);
    const card = page.getByTestId("env-context");
    await expect(card.getByText("COMPLETE", { exact: true })).toBeVisible();
    await page.waitForTimeout(1800);
    await expect(card.getByText("COMPLETE", { exact: true })).toBeVisible();
    await expect(card).not.toContainText(fixture("environment_context").reason);
  });

  test("switching upload clears the previous context before a failure", async ({ page, api }) => {
    api.allowConsoleError(/Failed to load resource/);
    api.override("GET", new RegExp(`^/reports/${OTHER}$`), { body: otherReport() });
    api.override("GET", /^\/environment\/uploads\/upl_e2e0000000002$/, { status: 503, body: { detail: "context service down" } });

    await page.goto(`/partner-report/academia?analysis_id=${ANALYSIS_ID}`);
    const card = page.getByTestId("env-context");
    const env = fixture("environment_context");
    await expect(card.getByText(env.reason)).toBeVisible();
    await pushUrl(page, `/partner-report/academia?analysis_id=${OTHER}`);
    await expect(card).toContainText("context service down");
    await expect(card).not.toContainText(env.reason);
    await expect(card.getByText("PENDING", { exact: true })).toHaveCount(0);
  });

  test("the any-rank basis names the legacy taxon source too", async ({ page }) => {
    const anyRank = fixture("partner_cooccurrence_any");
    await page.goto("/partner-report/academia");
    const basis = page.getByTestId("cooccurrence-basis");
    await expect(basis).toContainText("decision.predicted_taxon with decision.taxon_rank = species");
    await page.getByLabel("Taxonomic rank").selectOption("any");
    await expect(basis).toContainText(
      `plus ${anyRank.taxa_by_rank.unrecorded} legacy results[].predicted_taxon taxa whose rank was never recorded`);
  });

  for (const [name, impl, expected] of [
    ["a successful copy says Copied", "() => Promise.resolve()", "Copied ✓"],
    ["a refused copy says it failed", "() => Promise.reject(new DOMException('denied', 'NotAllowedError'))", "Could not copy to the clipboard"],
  ]) {
    test(`citation: ${name}`, async ({ page }) => {
      await page.addInitScript(`Object.defineProperty(navigator, "clipboard", { value: { writeText: ${impl} }, configurable: true });`);
      await page.goto("/partner-report/academia");
      await page.getByRole("button", { name: "Copy citation" }).click();
      await expect(page.getByText(expected)).toBeVisible();
      if (expected !== "Copied ✓") await expect(page.getByText("Copied ✓")).toHaveCount(0);
    });
  }
});
