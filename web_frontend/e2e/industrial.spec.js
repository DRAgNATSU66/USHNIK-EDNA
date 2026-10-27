// Industrial partner page (t-1028-2): every panel is fed by a recorded API
// fixture (partner_summary / partner_incidents / partner_tasks /
// partner_audits / reports_list / field_attachments, from
// services/api/scripts/gen_e2e_fixtures.py), the audit form shows the API's
// own 422 (partner_audit_create_422, also recorded), and the panels with no
// data source are gone.
import { test, expect, fixture, ANALYSIS_ID } from "./support/mockApi.js";

const incidents = fixture("partner_incidents");
const tasks = fixture("partner_tasks");
const [audit] = fixture("partner_audits");
const summary = fixture("partner_summary");
const [attachment] = fixture("field_attachments");

test.describe("industrial partner page", () => {
  test("renders incidents, audits, tasks and documents from the API", async ({ page, api }) => {
    await page.goto("/partner-report/industrial");
    await expect(page.getByRole("heading", { name: "Enterprise Compliance Dashboard" })).toBeVisible();

    // KPIs come straight from the fixtures.
    await expect(page.getByTestId("kpi-incidents")).toContainText(String(incidents.total));
    await expect(page.getByTestId("kpi-incidents")).toContainText(
      `${incidents.contamination_flags} contamination flag`);
    await expect(page.getByTestId("kpi-urgent")).toContainText(String(incidents.urgent_reviews_total));
    await expect(page.getByTestId("kpi-audits")).toContainText(String(summary.audits.pending));
    await expect(page.getByTestId("kpi-audits")).toContainText(`next due ${summary.audits.next_due_date}`);
    await expect(page.getByTestId("kpi-tasks")).toContainText(`${summary.tasks.overdue} overdue`);

    // Incidents: one row per flagged analysis, with its definition.
    const [inc] = incidents.incidents;
    const row = page.getByTestId("incident-row");
    await expect(row).toHaveCount(incidents.incidents.length);
    await expect(row.first()).toContainText(inc.source_file);
    await expect(row.first()).toContainText(`${inc.novelty_flags} novelty flags`);
    await expect(row.first()).toContainText(inc.flagged_sequences[0].sequence_id);
    await expect(page.getByText(incidents.definitions.incident)).toBeVisible();
    await expect(page.getByTestId("urgent-review")).toHaveCount(incidents.urgent_reviews.length);

    // Audit trail + tasks.
    await expect(page.getByTestId("audit-row").first()).toContainText(audit.target.label);
    await expect(page.getByTestId("audit-row").first()).toContainText(audit.findings[0].description);
    await expect(page.getByTestId("task-row")).toHaveCount(tasks.tasks.length);
    await expect(page.getByTestId("task-row").first()).toContainText("overdue");

    // Document hub: the analysis's real attachment, nothing invented.
    await expect(page.getByText(attachment.original_filename)).toBeVisible();

    // Panels with no data source are removed, and so is every MockTag.
    for (const gone of ["AVERAGE IMPACT SCORE", "ENVIRONMENTAL RISK RADAR", "BIOLOGICAL IMPACT METRICS",
      "REMEDIATION PLAN", "PREDICTIVE THRESHOLD", "REMEDIATION ROI", "MOCK — NO BACKEND YET", "MarineGenomeDB"]) {
      await expect(page.getByText(gone, { exact: false })).toHaveCount(0);
    }

    expect(api.called("GET /partner/summary?scope=mine")).toBe(true);
    expect(api.called("GET /partner/incidents?scope=mine")).toBe(true);
    expect(api.called("GET /partner/tasks?scope=mine")).toBe(true);
    expect(api.called("GET /partner/audits?created_by=usr_e2e_researcher")).toBe(true);
    expect(api.called(`GET /field-log/attachments?analysis_id=${ANALYSIS_ID}`)).toBe(true);
  });

  test("audit form shows the server's validation errors and records nothing", async ({ page, api }) => {
    api.override("POST", /^\/partner\/audits$/, { status: 422, body: fixture("partner_audit_create_422") });
    api.allowConsoleError(/status of 422/);
    await page.goto("/partner-report/industrial");
    await page.getByRole("button", { name: "Record audit" }).click();
    const alert = page.getByRole("alert").filter({ hasText: "the server refused it" });
    await expect(alert).toContainText("target.label: String should have at least 1 character");
    await expect(alert).toContainText("scope: String should have at least 1 character");
    await expect(page.getByTestId("audit-row")).toHaveCount(1);
    expect(api.called("POST /partner/audits")).toBe(true);
  });

  test("a recorded audit is added from the server's response", async ({ page, api }) => {
    let posted = null;
    // The response echoes the recorded AuditDoc shape with the submitted fields.
    api.override("POST", /^\/partner\/audits$/, () => ({
      status: 201,
      body: { ...audit, audit_id: "aud_e2e_recorded01", target: { kind: "site", ref: null, label: "Outfall zone B" },
        scope: "Effluent eDNA against the discharge permit", findings: [] },
    }));
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/partner/audits")) posted = r.postDataJSON();
    });
    await page.goto("/partner-report/industrial");
    await page.getByLabel("TARGET LABEL").fill("Outfall zone B");
    await page.getByLabel("SCOPE").fill("Effluent eDNA against the discharge permit");
    await page.getByLabel("DUE DATE").fill("2099-01-31");
    await page.getByRole("button", { name: "Record audit" }).click();
    await expect(page.getByRole("status")).toContainText("Recorded aud_e2e_recorded01");
    await expect(page.getByTestId("audit-row")).toHaveCount(2);
    await expect(page.getByTestId("audit-row").first()).toContainText("Outfall zone B");
    expect(posted).toEqual({
      target: { kind: "site", label: "Outfall zone B" },
      scope: "Effluent eDNA against the discharge permit",
      status: "scheduled",
      findings: [],
      due_date: "2099-01-31",
    });
  });

  test("custody verification is fetched on request", async ({ page, api }) => {
    // Minimal custody snapshot (GET /reports/{id}/custody writes derived
    // events and timestamps, so it is not recorded as a fixture).
    api.override("GET", /^\/reports\/[^/]+\/custody$/, {
      body: {
        analysis_id: ANALYSIS_ID, chain_id: "chain_e2e", events: [],
        verification: { valid: true, length: 3, head_hash: "ab".repeat(32), first_break: null, checked_at: "2026-10-16T09:00:00+00:00" },
        results_integrity: { status: "match" }, metadata_integrity: { status: "unchanged" }, file_integrity: { status: "not_checked" },
        notes: [],
      },
    });
    await page.goto("/partner-report/industrial");
    expect(api.called(`GET /reports/${ANALYSIS_ID}/custody`)).toBe(false);
    await page.getByRole("button", { name: "Verify chain of custody" }).click();
    const result = page.getByTestId("custody-result");
    await expect(result).toContainText("chain valid");
    await expect(result).toContainText("3 events");
    await expect(result).toContainText("results match");
  });

  test.describe("as admin", () => {
    test.use({ role: "admin" });

    test("scope switch re-queries every panel for all users", async ({ page, api }) => {
      await page.goto("/partner-report/industrial");
      await expect(page.getByTestId("incident-row").first()).toBeVisible();
      await page.getByRole("button", { name: "My data" }).click();
      await page.getByRole("button", { name: "All users" }).click();
      await expect.poll(() => api.called("GET /partner/incidents?scope=all")).toBe(true);
      expect(api.called("GET /partner/summary?scope=all")).toBe(true);
      expect(api.called("GET /partner/tasks?scope=all")).toBe(true);
      // All users: no created_by narrowing on audits.
      expect(api.calls).toContain("GET /partner/audits");
    });
  });
});

test.describe("industrial: expected-by-route contamination (QNA-030)", () => {
  test("is reported as a separate count, not as an incident", async ({ page, api }) => {
    const body = fixture("partner_incidents");
    body.expected_contamination_flags = 3;
    api.override("GET", /^\/partner\/incidents$/, { body });
    await page.goto("/partner-report/industrial");
    const note = page.getByTestId("expected-contamination");
    await expect(note).toContainText("Not counted as incidents: 3 expected contamination flags");
    await expect(note).toContainText(body.definitions.expected_contamination);
    await expect(page.getByTestId("kpi-incidents")).toContainText(`${body.contamination_flags} contamination flag`);
  });

  test("says nothing when there is none", async ({ page }) => {
    expect(incidents.expected_contamination_flags).toBe(0);
    await page.goto("/partner-report/industrial");
    await expect(page.getByTestId("incident-row").first()).toBeVisible();
    await expect(page.getByTestId("expected-contamination")).toHaveCount(0);
  });
});
