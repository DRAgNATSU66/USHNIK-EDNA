import { tokens, pillStyle } from "../shared/tokens";
import { formatIdentity, formatScore, ruleText } from "../../lib/decision";

// "Why this answer": renders one sequence's stored decision_trace
// {orchestrator_version, plan, evidence[], combine[]} exactly as the worker
// wrote it (services/worker/app/orchestrator/engine.py). Nothing here is
// recomputed -- every number shown is a number in the trace, and a field the
// trace lacks is shown as missing rather than filled in.

const mono = { fontFamily: "ui-monospace,monospace" };
const sectionLabel = { fontSize: 11, fontWeight: 600, letterSpacing: "0.09em", color: tokens.labelText };
const muted = { fontSize: 12, color: tokens.sectionSubtext, lineHeight: 1.5 };
const STATUS_TONE = { ok: "success", unavailable: "warning", skipped: "pending" };
const REF_STATUS_TONE = { assigned: "success", no_consensus: "warning", below_threshold: "warning", no_hit: "pending" };
const PROVIDER_LABEL = {
  route_head: "Route head",
  reference_lookup: "Reference lookup",
  contamination: "Contamination",
  novelty: "Novelty",
};
const STEP_LABEL = {
  route: "Route",
  taxon: "Taxon",
  class: "Class",
  novelty: "Novelty",
  contamination: "Contamination",
  disagreement: "Disagreement",
};

function Code({ children }) {
  return <span style={{ ...mono, fontSize: 11.5, color: tokens.wordmark }}>{children}</span>;
}

function Pill({ tone = "pending", children, title }) {
  return <span style={{ ...pillStyle(tone), fontSize: 11, padding: "2px 9px" }} title={title}>{children}</span>;
}

function KV({ items }) {
  const shown = items.filter(([, v]) => v !== undefined);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 16px", fontSize: 12 }}>
      {shown.map(([k, v]) => (
        <span key={k} style={{ color: tokens.sectionSubtext }}>
          {k} <span style={{ color: v == null ? tokens.pending : tokens.textPrimary }}>{v == null ? "—" : String(v)}</span>
        </span>
      ))}
    </div>
  );
}

function RouterBlock({ router }) {
  if (!router) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <KV
        items={[
          ["router", [router.method, router.version].filter(Boolean).join(" ") || null],
          ["calibrated", router.calibrated == null ? null : router.calibrated ? "yes" : "no"],
          ["top probability", router.top_probability],
          ["top-2 margin", router.margin],
        ]}
      />
      {Array.isArray(router.ranked) && router.ranked.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {router.ranked.map(([route, p]) => (
            <span key={route} style={{ ...mono, fontSize: 11.5, color: tokens.sectionSubtext }}>
              {route} <span style={{ color: tokens.textPrimary }}>{p}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function PlanSection({ plan }) {
  if (!plan) return <span style={muted}>The trace has no plan.</span>;
  const routes = plan.routes ?? [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>Routes considered</span>
        {routes.map((r) => (
          <Pill key={r} tone={r === plan.primary_route ? "accent" : "pending"} title={r === plan.primary_route ? "router's top pick" : undefined}>
            {r}{r === plan.primary_route ? " · router pick" : ""}
          </Pill>
        ))}
        {plan.max_routes != null && <span style={{ fontSize: 11.5, color: tokens.pending }}>cap {plan.max_routes}</span>}
      </div>
      <RouterBlock router={plan.router} />
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {(plan.rules_fired ?? []).map((rf, i) => (
          <div key={`${rf.rule}-${i}`} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 12.5, color: tokens.textPrimary }}>
              <Code>{rf.rule}</Code> <span style={{ color: tokens.pending }}>({rf.stage})</span> — {ruleText(rf.rule)}
              {rf.added?.length > 0 && <span style={{ color: tokens.accentCyan }}> · added {rf.added.join(", ")}</span>}
            </span>
            {rf.detail && <span style={{ ...muted, paddingLeft: 12 }}>{rf.detail}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}

function HitsTable({ hits }) {
  if (!hits?.length) return null;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", fontSize: 11.5, color: tokens.sectionSubtext, minWidth: 460 }}>
        <thead>
          <tr style={{ color: tokens.pending, textAlign: "left" }}>
            {["accession", "taxon", "rank", "identity", "coverage", "marker", "source"].map((h) => (
              <th key={h} style={{ padding: "3px 10px 3px 0", fontWeight: 500 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hits.map((h, i) => (
            <tr key={`${h.accession}-${i}`}>
              <td style={{ padding: "3px 10px 3px 0", ...mono }}>{h.accession ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0", fontStyle: "italic", color: tokens.textPrimary }}>{h.taxon ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0" }}>{h.rank ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0" }}>{formatIdentity(h.identity) ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0" }}>{formatIdentity(h.query_coverage) ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0" }}>{h.marker ?? "—"}</td>
              <td style={{ padding: "3px 10px 3px 0" }}>{h.source ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// GRCh38 states, as reference_lookup._human_genome writes them: hit=true
// passed the identity/coverage thresholds; hit=false with an identity is the
// best hit falling below them (the worker's reason says by how much);
// hit=false with no identity is no hit at all.
function humanGenomeState(hg) {
  if (hg.contamination) return { tone: "danger", label: "human contamination" };
  if (hg.hit) return { tone: "warning", label: "hit, beaten by a closer assignment" };
  if (hg.identity != null) return { tone: "pending", label: "below threshold" };
  return { tone: "pending", label: "no hit" };
}

function HumanGenome({ hg }) {
  if (!hg) return null;
  if (hg.available === false) return <span style={muted}>GRCh38 search unavailable{hg.reason ? `: ${hg.reason}` : ""}</span>;
  const state = humanGenomeState(hg);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>GRCh38</span>
        <Pill tone={state.tone}>{state.label}</Pill>
        <KV items={[["identity", formatIdentity(hg.identity)], ["coverage", formatIdentity(hg.query_coverage)], ["subject", hg.subject]]} />
      </div>
      {hg.reason && <span style={muted}>{hg.reason}</span>}
    </div>
  );
}

function ProviderPayload({ rec }) {
  const p = rec.payload ?? {};
  switch (rec.provider) {
    case "route_head":
      return (
        <KV
          items={[
            ["class", p.result_class],
            ["score", formatScore(p.confidence)],
            ["model", p.model_version_used],
            ["mode", p.inference_mode],
            ...(p.stub_reason ? [["stub reason", p.stub_reason]] : []),
          ]}
        />
      );
    case "reference_lookup":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <Pill tone={REF_STATUS_TONE[p.status] ?? "pending"}>{p.status ?? "no status"}</Pill>
            {p.taxon && (
              <span style={{ fontSize: 12.5, color: tokens.textPrimary }}>
                <i>{p.taxon}</i> <span style={{ color: tokens.pending }}>({p.rank ?? "rank —"})</span>
              </span>
            )}
          </div>
          <KV
            items={[
              ["identity", formatIdentity(p.identity)],
              ["coverage", formatIdentity(p.query_coverage)],
              ["tied hits / taxa", p.tied_hits != null ? `${p.tied_hits} / ${p.tied_taxa ?? "—"}` : null],
              ["LCA applied", p.lca_applied == null ? null : p.lca_applied ? "yes" : "no"],
              ["DB", p.reference_db ? `${p.reference_db} ${p.reference_db_version ?? ""}`.trim() : null],
              ["method", p.method],
            ]}
          />
          {p.reason && <span style={muted}>{p.reason}</span>}
          <HitsTable hits={p.hits} />
          <HumanGenome hg={p.human_genome} />
        </div>
      );
    case "contamination":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <KV
            items={[
              ["score", p.contamination_score],
              ["flagged", p.flagged == null ? null : p.flagged ? "yes" : "no"],
              ["type", p.contamination_type],
              ["GRCh38 contamination", p.grch38_contamination == null ? undefined : p.grch38_contamination ? "yes" : "no"],
            ]}
          />
          {p.reason_codes?.length > 0 && <span style={{ ...muted, ...mono, fontSize: 11 }}>{p.reason_codes.join(" · ")}</span>}
        </div>
      );
    case "novelty":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <KV items={[["raw score", p.novelty_score], ["level", p.novelty_level], ["recommendation", p.abyss_recommendation]]} />
          {p.reason_codes?.length > 0 && <span style={{ ...muted, ...mono, fontSize: 11 }}>{p.reason_codes.join(" · ")}</span>}
        </div>
      );
    default: {
      const scalars = Object.entries(p).filter(([, v]) => v == null || typeof v !== "object");
      return <KV items={scalars} />;
    }
  }
}

function EvidenceRecord({ rec }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: "10px 12px", borderRadius: 6, border: "1px solid #132238", background: "rgba(8,14,26,0.5)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: tokens.textPrimary }}>{PROVIDER_LABEL[rec.provider] ?? rec.provider}</span>
        {rec.provider_version && <span style={{ fontSize: 11, color: tokens.pending }}>v{rec.provider_version}</span>}
        <Pill tone={STATUS_TONE[rec.status] ?? "pending"}>{rec.status}</Pill>
        {rec.elapsed_ms != null && <span style={{ fontSize: 11, color: tokens.pending }}>{rec.elapsed_ms} ms</span>}
      </div>
      {rec.status !== "ok" ? (
        <span style={{ ...muted, color: tokens.warning }}>{rec.reason || "No reason recorded."}</span>
      ) : (
        <ProviderPayload rec={rec} />
      )}
    </div>
  );
}

function EvidenceSection({ evidence, routes }) {
  if (!evidence?.length) return <span style={muted}>The trace has no evidence records.</span>;
  const order = [...(routes ?? [])];
  for (const e of evidence) if (!order.includes(e.route)) order.push(e.route);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {order.map((route) => {
        const recs = evidence.filter((e) => e.route === route);
        if (recs.length === 0) return null;
        return (
          <div key={route} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ ...mono, fontSize: 12, color: tokens.accentCyan }}>{route}</span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 8 }}>
              {recs.map((rec, i) => <EvidenceRecord key={`${rec.provider}-${i}`} rec={rec} />)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Outcome({ value }) {
  if (value == null) return <span style={{ color: tokens.pending }}>—</span>;
  if (typeof value !== "object") return <Code>{String(value)}</Code>;
  return (
    <span style={{ display: "inline-flex", flexWrap: "wrap", gap: "2px 12px" }}>
      {Object.entries(value).map(([k, v]) => (
        <span key={k} style={{ fontSize: 11.5, color: tokens.sectionSubtext }}>
          {k} <Code>{v == null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}</Code>
        </span>
      ))}
    </span>
  );
}

function stepTone(s) {
  if (s.step === "disagreement") return "warning";
  if (s.rule === "genus_cap") return "warning";
  if (s.rule === "novelty_suppressed_by_reference" || s.rule === "novelty_downgraded_by_reference") return "purple";
  if (s.rule === "grch38_beaten_by_closer_assignment") return "warning";
  return "accent";
}

function CombineSection({ combine }) {
  if (!combine?.length) return <span style={muted}>The trace has no combine steps.</span>;
  return (
    <ol style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 8 }}>
      {combine.map((s, i) => {
        const nov = s.step === "novelty" && s.outcome && typeof s.outcome === "object" ? s.outcome : null;
        return (
          <li key={`${s.step}-${s.rule}-${i}`} style={{ color: tokens.textPrimary }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 12.5 }}>
                <Pill tone={stepTone(s)}>{STEP_LABEL[s.step] ?? s.step}</Pill>
                <Code>{s.rule}</Code>
                <span>{ruleText(s.rule)}</span>
              </span>
              {s.rule === "genus_cap" && s.outcome ? (
                <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
                  <i>{s.outcome.from}</i> → <i style={{ color: tokens.textPrimary }}>{s.outcome.to}</i>
                </span>
              ) : nov ? (
                <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
                  raw score <Code>{nov.raw_score ?? "—"}</Code> × gate <Code>{nov.gate ?? "—"}</Code> = <Code>{nov.final_score ?? "—"}</Code>
                  {nov.suppressed_by_reference && <span style={{ color: tokens.purple }}> · novelty flag suppressed by reference</span>}
                  {nov.downgraded_by_reference && <span style={{ color: tokens.purple }}> · downgraded by reference, kept for review</span>}
                  {!nov.suppressed_by_reference && !nov.downgraded_by_reference && (
                    <span> · flag {nov.raw_flag ? "raised" : "not raised"} → {nov.final_flag ? "raised" : "not raised"}</span>
                  )}
                </span>
              ) : (
                <span style={{ fontSize: 12, color: tokens.sectionSubtext }}>
                  outcome <Outcome value={s.outcome} />
                </span>
              )}
              {s.detail && <span style={{ ...muted, fontSize: 11.5 }}>{s.detail}</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * @param {object|null} trace - the row's decision_trace
 * @param {object|null} decision - the row's decision (rule, final_route)
 * @param {"loading"|"error"|"ready"} status - trace fetch state
 * @param {string} [error]
 */
export default function DecisionTrace({ trace, decision, status, error, onRetry }) {
  const box = { display: "flex", flexDirection: "column", gap: 16, padding: "16px 18px", borderRadius: 8, border: "1px solid #17263F", background: "rgba(4,8,16,0.6)" };

  if (!decision) {
    return (
      <div style={box} data-testid="decision-trace">
        <span style={{ fontSize: 13, color: tokens.wordmark }}>No decision trace exists for this sequence.</span>
        <span style={muted}>
          It was analysed before the orchestrator (decision Q7) was deployed, so the stored result has no plan, evidence
          or combine steps: its route and class come from the router and a single route head, and no reference evidence
          was stored with it.
        </span>
      </div>
    );
  }
  if (status === "loading") {
    return <div style={box} data-testid="decision-trace"><span style={muted}>Loading decision traces…</span></div>;
  }
  if (status === "error") {
    return (
      <div style={box} data-testid="decision-trace">
        <span style={{ fontSize: 13, color: tokens.danger }}>Could not load the decision trace{error ? `: ${error}` : "."}</span>
        {onRetry && (
          <button type="button" onClick={onRetry} style={{ alignSelf: "flex-start", padding: "6px 14px", borderRadius: 8, border: `1px solid ${tokens.sectionBorder}`, background: "#080F1C", color: tokens.wordmark, fontFamily: "inherit", fontSize: 12.5, cursor: "pointer" }}>
            Retry
          </button>
        )}
      </div>
    );
  }
  if (!trace) {
    return (
      <div style={box} data-testid="decision-trace">
        <span style={{ fontSize: 13, color: tokens.wordmark }}>This sequence has a decision but no stored trace.</span>
        <span style={muted}>The API returned no decision_trace for it; the decision above is all that was stored.</span>
      </div>
    );
  }

  return (
    <div style={box} data-testid="decision-trace">
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12.5, color: tokens.sectionSubtext }}>
          Decided by <Code>{decision.rule ?? "—"}</Code> on route <Code>{decision.final_route ?? "—"}</Code>
        </span>
        {trace.orchestrator_version && <span style={{ fontSize: 11, color: tokens.pending }}>{trace.orchestrator_version}</span>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={sectionLabel}>1 · PLAN</span>
        <PlanSection plan={trace.plan} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={sectionLabel}>2 · EVIDENCE</span>
        <EvidenceSection evidence={trace.evidence} routes={trace.plan?.routes} />
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <span style={sectionLabel}>3 · COMBINE</span>
        <CombineSection combine={trace.combine} />
      </div>
    </div>
  );
}
