// Upload "Auto" (orchestrator) panel and the Results page's per-sequence
// calls + "Why this answer" decision trace (t-1023-2; decision Q7). The
// fixtures are recorded from the real API by services/api/scripts/
// gen_e2e_fixtures.py: an orchestrated analysis (decisions + traces), a
// pre-orchestrator one (neither), and /models/status.
import { test, expect, fixture, LEGACY_ANALYSIS_ID, ORCH_ANALYSIS_ID } from "./support/mockApi.js";

const status = fixture("models_status");
const routerId = fixture("models_registry").selected_by_route.router;
const orch = fixture("analysis_orchestrated_trace");
const row = (id) => orch.results.find((r) => r.sequence_id === id);

test.describe("upload: Auto processing model", () => {
  test("shows Auto and the heads /models/status reports, not a fake picker", async ({ page, api }) => {
    await page.goto("/upload");
    await expect(page.getByRole("heading", { name: "New Analysis" })).toBeVisible();
    await expect(page.getByRole("radio", { name: /Auto/ })).toHaveAttribute("aria-checked", "true");
    await expect(page.getByText("Orchestrator", { exact: true })).toBeVisible();
    const list = page.getByTestId("served-models");
    for (const r of Object.values(status.routes)) {
      await expect(list.getByText(r.model_id, { exact: true })).toBeVisible();
    }
    await expect(list.getByText(routerId, { exact: true })).toBeVisible();
    // The recorded fixture pins a data root with no artifacts: every head
    // reads missing_artifacts, and the page says the worker would stub it.
    await expect(list.getByText("files missing — stub")).toHaveCount(Object.keys(status.routes).length);
    // The removed picker named models that never existed.
    await expect(page.getByText("AbyssNet v3")).toHaveCount(0);
    await expect(page.getByText("MetaGen Ensemble")).toHaveCount(0);
    expect(api.called("GET /models/status")).toBe(true);
  });

  test("a ready head reads as served", async ({ page, api }) => {
    const body = fixture("models_status");
    body.routes.fish = { ...body.routes.fish, status: "ready", reason: "artifacts_resolved", inference_mode: "model" };
    api.override("GET", /^\/models\/status$/, { body });
    await page.goto("/upload");
    const list = page.getByTestId("served-models");
    await expect(list.getByText("served", { exact: true })).toHaveCount(1);
    await expect(list.getByText("files missing — stub")).toHaveCount(Object.keys(body.routes).length - 1);
  });

  test("an unavailable /models/status is said, not hidden", async ({ page, api }) => {
    api.allowConsoleError(/503/);
    api.override("GET", /^\/models\/status$/, { status: 503, body: { detail: "registry unreadable" } });
    await page.goto("/upload");
    await expect(page.getByText(/Model status unavailable \(registry unreadable\)/)).toBeVisible();
    await expect(page.getByRole("radio", { name: /Auto/ })).toHaveAttribute("aria-checked", "true");
  });
});

test.describe("results: sequence calls and decision trace", () => {
  test("rows show taxon, rank, identity, reference DB and head score; traces load on first expand", async ({ page, api }) => {
    await page.goto(`/analysis/${ORCH_ANALYSIS_ID}`);
    await expect(page.getByRole("heading", { name: "Analysis Report" })).toBeVisible();
    const rows = page.getByTestId("sequence-call");
    await expect(rows).toHaveCount(orch.results.length);

    const tuna = rows.filter({ hasText: "seq_e2e_orch_tuna_01" });
    const d = row("seq_e2e_orch_tuna_01").decision;
    await expect(tuna.getByText(d.predicted_taxon, { exact: true })).toBeVisible();
    await expect(tuna.getByText(d.taxon_rank, { exact: true })).toBeVisible();
    await expect(tuna.getByText(`${d.percent_identity}%`, { exact: true })).toBeVisible();
    await expect(tuna.getByText(`Reference DB: ${d.reference_db} v2`, { exact: false })).toBeVisible();
    await expect(tuna.getByText(/dnabert2_fish_v2 class score · Confidence: 97\.0% \(uncalibrated\)/)).toBeVisible();

    // Reference evidence moved this read off the router's pick.
    await expect(rows.filter({ hasText: "seq_e2e_orch_mussel_03" }).getByText("router picked misc_unknown")).toBeVisible();
    // A reference miss: searched, no assignment.
    await expect(rows.filter({ hasText: "seq_e2e_orch_vent_04" }).getByText("No reference assignment")).toBeVisible();

    // Rows load without traces; no trace request until a row is opened.
    expect(api.called(`GET /analysis/${ORCH_ANALYSIS_ID}?include_trace=false`)).toBe(true);
    expect(api.called(`GET /analysis/${ORCH_ANALYSIS_ID}?include_trace=true`)).toBe(false);

    const oak = rows.filter({ hasText: "seq_e2e_orch_oak_02" });
    await oak.getByRole("button", { name: "Why this answer" }).click();
    const trace = oak.getByTestId("decision-trace");
    await expect(trace.getByText("1 · PLAN")).toBeVisible();
    await expect(trace.getByText("low_confidence", { exact: true })).toBeVisible();
    await expect(trace.getByText("top probability 0.58 < 0.7")).toBeVisible();
    // Evidence: the unavailable provider's reason is shown.
    await expect(trace.getByText("BLAST database for misc_unknown not found on the worker")).toBeVisible();
    // Combine: plant capped at genus, novelty downgraded but kept.
    await expect(trace.getByText("genus_cap", { exact: true })).toBeVisible();
    await expect(trace.getByText("Quercus robur", { exact: true }).first()).toBeVisible();
    await expect(trace.getByText(/downgraded by reference, kept for review/)).toBeVisible();

    const mussel = rows.filter({ hasText: "seq_e2e_orch_mussel_03" });
    await mussel.getByRole("button", { name: "Why this answer" }).click();
    const mtrace = mussel.getByTestId("decision-trace");
    await expect(mtrace.getByText("reference_overrides_router", { exact: true })).toBeVisible();
    await expect(mtrace.getByText(/novelty flag suppressed by reference/)).toBeVisible();

    // One request brought every trace.
    expect(api.calls.filter((c) => c === `GET /analysis/${ORCH_ANALYSIS_ID}?include_trace=true`)).toHaveLength(1);
    // Footer names the shared reference root and version.
    await expect(page.getByText("Reference DB: synthveda-reference (4 route DBs) v2", { exact: false })).toBeVisible();
  });

  test("a pre-orchestrator analysis says no trace exists", async ({ page, api }) => {
    const legacy = fixture("analysis_legacy");
    await page.goto(`/analysis/${LEGACY_ANALYSIS_ID}`);
    await expect(page.getByText(/stored before the orchestrator: no row has a decision/)).toBeVisible();
    const rows = page.getByTestId("sequence-call");
    await expect(rows).toHaveCount(legacy.results.length);
    await expect(rows.first().getByText("Reference DB: none recorded (pre-orchestrator result)")).toBeVisible();
    await expect(rows.filter({ hasText: "seq_e2e_old_02" }).getByText(/stub inference \(no head weights\)/)).toBeVisible();
    await rows.first().getByRole("button", { name: "Why this answer" }).click();
    await expect(rows.first().getByText("No decision trace exists for this sequence.")).toBeVisible();
    expect(api.called(`GET /reports/${LEGACY_ANALYSIS_ID}`)).toBe(true);
    expect(api.called(`GET /analysis/${LEGACY_ANALYSIS_ID}?include_trace=true`)).toBe(false);
  });

  test("a reference search with no assignment is not tagged as a match", async ({ page }) => {
    await page.goto(`/analysis/${ORCH_ANALYSIS_ID}`);
    const rows = page.getByTestId("sequence-call");
    const vent = rows.filter({ hasText: "seq_e2e_orch_vent_04" });
    const d = row("seq_e2e_orch_vent_04").decision;
    expect(d.reference_db).toBeTruthy();
    expect(d.predicted_taxon).toBeNull();
    const tag = vent.getByText(`Reference DB: ${d.reference_db} v2`, { exact: false });
    await expect(tag).toContainText(/· Searched .+ · no assignment$/);
    await expect(tag).not.toContainText("Matched");
    // An assigned row still reads "Matched".
    await expect(rows.filter({ hasText: "seq_e2e_orch_tuna_01" }).getByText(/· Matched /)).toBeVisible();
  });

  test("a below-threshold GRCh38 hit says so and shows the worker's reason", async ({ page, api }) => {
    const body = fixture("analysis_orchestrated_trace");
    const vent = body.results.find((r) => r.sequence_id === "seq_e2e_orch_vent_04");
    const ref = vent.decision_trace.evidence.find((e) => e.provider === "reference_lookup");
    const reason = "best GRCh38 hit 95% over 60% of the query is below 98%/80%";
    ref.payload.human_genome = {
      available: true, hit: false, contamination: false, identity: 95.0, query_coverage: 60.0,
      alignment_length: 180, subject: "NC_000001.11", start: 100, end: 280, reason,
    };
    api.override("GET", new RegExp(`^/analysis/${ORCH_ANALYSIS_ID}$`), (_m, url) =>
      url.searchParams.get("include_trace") === "false" ? "analysis_orchestrated" : { body });
    await page.goto(`/analysis/${ORCH_ANALYSIS_ID}`);
    const rowEl = page.getByTestId("sequence-call").filter({ hasText: "seq_e2e_orch_vent_04" });
    await rowEl.getByRole("button", { name: "Why this answer" }).click();
    const trace = rowEl.getByTestId("decision-trace");
    await expect(trace.getByText("below threshold", { exact: true })).toBeVisible();
    await expect(trace.getByText(reason)).toBeVisible();
    await expect(trace.getByText("no hit", { exact: true })).toHaveCount(0);
  });

  test("moving to another analysis drops the previous analysis's traces", async ({ page, api }) => {
    // A second orchestrated analysis: the same rows under another id.
    const otherId = "ana_e2e00000000b2";
    const rowsBody = { ...fixture("analysis_orchestrated"), analysis_id: otherId };
    const traceBody = { ...fixture("analysis_orchestrated_trace"), analysis_id: otherId };
    const report = fixture("report_orchestrated");
    report.metadata.analysis_id = otherId;
    api.override("GET", new RegExp(`^/reports/${otherId}$`), { body: report });
    api.override("GET", new RegExp(`^/analysis/${otherId}$`), (_m, url) =>
      ({ body: url.searchParams.get("include_trace") === "false" ? rowsBody : traceBody }));

    await page.goto(`/analysis/${ORCH_ANALYSIS_ID}`);
    const tuna = () => page.getByTestId("sequence-call").filter({ hasText: "seq_e2e_orch_tuna_01" });
    await tuna().getByRole("button", { name: "Why this answer" }).click();
    await expect(tuna().getByTestId("decision-trace").getByText("1 · PLAN")).toBeVisible();

    // Client-side navigation: React Router keeps AnalysisResults mounted.
    await page.evaluate((id) => {
      window.history.pushState({}, "", `/analysis/${id}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    }, otherId);
    await expect(page.getByText(`Run ID ${otherId}`)).toBeVisible();
    // The open row and the loaded traces did not carry over.
    await expect(tuna().getByRole("button", { name: "Why this answer" })).toBeVisible();
    await tuna().getByRole("button", { name: "Why this answer" }).click();
    await expect(tuna().getByTestId("decision-trace").getByText("1 · PLAN")).toBeVisible();
    await expect(tuna().getByText(/no stored trace/)).toHaveCount(0);
    expect(api.called(`GET /analysis/${otherId}?include_trace=true`)).toBe(true);
  });
});

test.describe("species correction: reference provenance", () => {
  test("orchestrated rows say which reference DB they were matched against", async ({ page, api }) => {
    const rep = fixture("report_orchestrated");
    const tunaRow = rep.taxonomic_assignments.find((r) => r.sequence_id === "seq_e2e_orch_tuna_01");
    await page.goto(`/researcher-mode/species-correction?analysis_id=${ORCH_ANALYSIS_ID}`);
    await expect(page.getByRole("heading", { name: "Species Correction" })).toBeVisible();
    await expect(page.getByText(`${tunaRow.reference_db} v2`, { exact: true })).toBeVisible();
    await expect(page.getByText("not recorded", { exact: true })).toHaveCount(0);
    // Header and footer name the reference DBs too, not "pending configuration".
    await expect(page.getByText(/Reference DB: synthveda-reference \(\d+ route DBs\) v2/)).toHaveCount(2);
    await expect(page.getByText("Reference DB: pending configuration")).toHaveCount(0);
    expect(api.called(`GET /reports/${ORCH_ANALYSIS_ID}`)).toBe(true);
  });
});

test.describe("upload: keyboard", () => {
  test("the Auto processing model can be focused", async ({ page }) => {
    await page.goto("/upload");
    const auto = page.getByRole("radio", { name: /Auto/ });
    await auto.focus();
    await expect(auto).toBeFocused();
    await expect(auto).toHaveAttribute("tabindex", "0");
  });
});
