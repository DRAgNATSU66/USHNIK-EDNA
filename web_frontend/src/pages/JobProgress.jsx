import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import SidebarMenu from "../components/sidebar/SidebarMenu";
import MatrixRain from "../components/upload/MatrixRain";
import { getJob } from "../lib/api";
import {
  jobColors,
  circleWrapStyle,
  spinnerRingStyle,
  circleCoreStyle,
  stepLabelStyle,
  connectorTrackStyle,
  connectorFillStyle,
  metaChipStyle,
  metaChipValueStyle,
} from "./jobProgressStyles";

const STEPS = [
  { key: "queued", label: "Queued" },
  { key: "parsing", label: "Parsing sequences" },
  { key: "qc", label: "Quality control" },
  { key: "routing", label: "Taxonomic routing" },
  { key: "inferencing", label: "Running inference" },
  { key: "novelty_scoring", label: "Novelty scoring" },
  { key: "reporting", label: "Building report" },
  { key: "completed", label: "Complete" },
];

const POLL_MS = 600;
const STEP_ADVANCE_MS = 420;
const REDIRECT_DELAY_MS = 700;

function CheckIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path
        d="M5 12.5l4.2 4.2L19 7"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="24"
        strokeDashoffset="24"
        style={{ animation: "sv-tick-draw .4s ease forwards" }}
      />
    </svg>
  );
}

function FailIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

function StepCircle({ step, index, status }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: "0 0 auto" }}>
      <div style={circleWrapStyle()}>
        {status === "active" && <div style={spinnerRingStyle} />}
        <div
          style={{
            ...circleCoreStyle(status),
            animation: status === "done" || status === "failed" ? "sv-step-pop .3s ease" : "none",
          }}
        >
          {status === "done" ? <CheckIcon /> : status === "failed" ? <FailIcon /> : index + 1}
        </div>
      </div>
      <div style={stepLabelStyle(status)}>{step.label}</div>
    </div>
  );
}

function Stepper({ displayedIndex, failed }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", width: "100%", maxWidth: 980 }}>
      {STEPS.map((step, i) => {
        const status =
          i < displayedIndex ? "done" : i === displayedIndex ? (failed ? "failed" : "active") : "pending";
        return (
          <div key={step.key} style={{ display: "flex", alignItems: "flex-start", flex: i === STEPS.length - 1 ? "0 0 auto" : "1 1 auto" }}>
            <StepCircle step={step} index={i} status={status} />
            {i < STEPS.length - 1 && (
              <div style={connectorTrackStyle()}>
                <div style={connectorFillStyle(i < displayedIndex)} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function JobProgress() {
  const { job_id } = useParams();
  const navigate = useNavigate();
  const [job, setJob] = useState(null);
  const [fetchError, setFetchError] = useState("");
  const [displayedIndex, setDisplayedIndex] = useState(0);
  const redirectedRef = useRef(false);

  // Poll the real job status.
  useEffect(() => {
    let cancelled = false;
    let intervalId;

    const poll = async () => {
      try {
        const data = await getJob(job_id);
        if (cancelled) return;
        setJob(data);
        if (data.state === "completed" || data.state === "failed") {
          clearInterval(intervalId);
        }
      } catch (e) {
        if (cancelled) return;
        setFetchError(e.message || "Failed to load job status.");
        clearInterval(intervalId);
      }
    };

    poll();
    intervalId = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [job_id]);

  const isFailed = job?.state === "failed";

  // Walk the displayed checkpoint forward one at a time toward whatever the
  // backend has actually reached — never jump straight to the end, so every
  // real step is visible. Each step's active/spinning duration is however
  // long polling actually took to see it finish (real pipeline speed); the
  // fixed STEP_ADVANCE_MS is just the fill/tick transition itself, not a
  // simulated wait.
  useEffect(() => {
    if (!job || isFailed) return;
    const targetIndex = STEPS.findIndex((s) => s.key === job.state);
    if (targetIndex < 0 || displayedIndex >= targetIndex) return;
    const t = setTimeout(() => setDisplayedIndex((i) => i + 1), STEP_ADVANCE_MS);
    return () => clearTimeout(t);
  }, [job, isFailed, displayedIndex]);

  // Auto-redirect to the report once the final checkpoint has actually
  // played out — no manual "View Report" click.
  useEffect(() => {
    if (redirectedRef.current) return;
    if (job?.state === "completed" && job.analysis_id && displayedIndex === STEPS.length - 1) {
      redirectedRef.current = true;
      const t = setTimeout(() => {
        navigate(`/analysis/${job.analysis_id}`, { replace: true });
      }, REDIRECT_DELAY_MS);
      return () => clearTimeout(t);
    }
  }, [job, displayedIndex, navigate]);

  return (
    <div style={{ background: jobColors.pageBg, minHeight: "100vh" }}>
      <SidebarMenu />
      <div
        style={{
          minHeight: "100vh",
          position: "relative",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "80px 24px",
          boxSizing: "border-box",
        }}
      >
        <MatrixRain />
        <div
          style={{
            position: "absolute",
            inset: 0,
            pointerEvents: "none",
            background:
              "radial-gradient(52% 40% at 50% -4%, rgba(20,110,255,0.14) 0%, rgba(2,6,15,0) 60%), radial-gradient(46% 46% at 96% 44%, rgba(40,130,255,0.10) 0%, rgba(2,6,15,0) 60%)",
          }}
        />

        {fetchError && (
          <div style={{ position: "relative", textAlign: "center", color: jobColors.errorText, maxWidth: 420 }}>
            <div style={{ marginBottom: 14 }}>{fetchError}</div>
            <Link to="/upload" style={{ color: jobColors.accentBlue, textDecoration: "none", fontSize: 13.5 }}>
              ← New Analysis
            </Link>
          </div>
        )}

        {!fetchError && !job && (
          <div style={{ position: "relative", color: jobColors.headerMuted, fontSize: 14 }}>
            Loading job status...
          </div>
        )}

        {!fetchError && job && (
          <div
            style={{
              position: "relative",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 40,
              width: "100%",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <svg width="20" height="20" viewBox="0 0 26 26" fill="none">
                <path d="M6 2c0 6 14 8 14 13S6 20 6 24" stroke={jobColors.accentBlue} strokeWidth="2" strokeLinecap="round" />
                <path d="M20 2c0 6-14 8-14 13s14 5 14 9" stroke={jobColors.accentCyan} strokeWidth="2" strokeLinecap="round" />
              </svg>
              <span style={{ fontWeight: 600, letterSpacing: "0.28em", fontSize: 12, color: jobColors.wordmark }}>
                SYNTH VEDA
              </span>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 10 }}>
              <span style={metaChipStyle}>
                Job <span style={metaChipValueStyle}>{job.job_id}</span>
              </span>
              <span style={metaChipStyle}>
                Upload <span style={metaChipValueStyle}>{job.upload_id}</span>
              </span>
              <span style={metaChipStyle}>
                Mode <span style={metaChipValueStyle}>{(job.mode || "").replace(/_/g, " ")}</span>
              </span>
            </div>

            <Stepper displayedIndex={displayedIndex} failed={isFailed} />

            {isFailed && (
              <div style={{ textAlign: "center", maxWidth: 460 }}>
                <div
                  style={{
                    padding: "12px 16px",
                    borderRadius: 10,
                    background: jobColors.errorBg,
                    border: `1px solid ${jobColors.errorBorder}`,
                    color: jobColors.errorText,
                    fontSize: 13.5,
                    marginBottom: 14,
                  }}
                >
                  {job.error_message || "Analysis failed."}
                </div>
                <Link to="/upload" style={{ color: jobColors.accentBlue, textDecoration: "none", fontSize: 13.5 }}>
                  ← Try again
                </Link>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
