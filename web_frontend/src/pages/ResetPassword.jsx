import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { supabase } from "../lib/supabaseClient";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authErrorStyle,
} from "../components/auth/authStyles";

function ResetPasswordForm() {
  const { confirmPasswordReset } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await confirmPasswordReset(password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Could not reset password. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Set a new password
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Choose a new password for your <span style={{ color: authColors.accentBlue }}>analysis workspace</span>.
      </p>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>New password</span>
          <input
            type="password"
            required
            placeholder="At least 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="sv-auth-input" style={authInputStyle}
          />
        </label>
        <label style={authLabelStyle}>
          <span style={authLabelTextStyle}>Confirm new password</span>
          <input
            type="password"
            required
            placeholder="Re-enter your new password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="sv-auth-input" style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Saving..." : "Save new password"}
        </button>
      </form>

      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

/**
 * Shown when the page was opened without a genuine password-recovery
 * context (e.g. someone just navigating to /reset-password directly).
 * Without this gate, confirmPasswordReset() would call
 * supabase.auth.updateUser() against *whatever* Supabase session happens
 * to exist in the browser — not necessarily one created by a real reset
 * link — which is exactly the session-hijack this page must not allow.
 */
function InvalidResetLink() {
  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Link invalid or expired
      </h2>
      <div style={authErrorStyle}>
        This password reset link is invalid or has expired.
      </div>
      <p style={{ marginTop: 24, fontSize: 13, color: authColors.textMuted, textAlign: "center" }}>
        <Link to="/forgot-password" style={{ color: authColors.accentBlue }}>Request a new reset link</Link>
      </p>
    </>
  );
}

function CheckingResetLink() {
  return (
    <p style={{ fontSize: 15, color: authColors.textSecondary, textAlign: "center" }}>
      Verifying your reset link...
    </p>
  );
}

export default function ResetPassword() {
  // "checking" | "valid" | "invalid" — gate the form on a genuine
  // Supabase password-recovery context, not just "some session exists".
  const [status, setStatus] = useState("checking");

  useEffect(() => {
    if (!supabase) {
      setStatus("invalid");
      return undefined;
    }

    // Primary check: Supabase's default (implicit) flow redirects back from
    // the reset email with `#access_token=...&type=recovery&...` in the URL
    // hash. This is synchronous and doesn't race the client's async
    // initialization, unlike waiting on an auth event alone.
    if (window.location.hash.includes("type=recovery")) {
      setStatus("valid");
      return undefined;
    }

    // Fallback: subscribe for the PASSWORD_RECOVERY auth event in case the
    // client finishes parsing/establishing the recovery session slightly
    // after this component mounts.
    const { data: listener } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") {
        setStatus("valid");
      }
    });

    // If neither the hash nor the event confirms a recovery context within
    // a short window, there isn't one — show the invalid/expired message
    // instead of rendering the password form.
    const timer = setTimeout(() => {
      setStatus((current) => (current === "checking" ? "invalid" : current));
    }, 2000);

    return () => {
      clearTimeout(timer);
      listener?.subscription?.unsubscribe();
    };
  }, []);

  let content;
  if (status === "valid") {
    content = <ResetPasswordForm />;
  } else if (status === "invalid") {
    content = <InvalidResetLink />;
  } else {
    content = <CheckingResetLink />;
  }

  return (
    <AuthLayout topRightPrompt="Remembered it?" topRightLabel="Sign in" topRightHref="/login">
      {content}
    </AuthLayout>
  );
}
