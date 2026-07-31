import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authErrorStyle,
  authInfoStyle,
} from "../components/auth/authStyles";

function ForgotPasswordForm() {
  const { requestPasswordReset } = useAuth();
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Reset your password
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Enter your email and we'll send you a link to get back into your <span style={{ color: authColors.accentBlue }}>analysis workspace</span>.
      </p>

      {sent ? (
        <div style={{ ...authInfoStyle, textAlign: "left" }}>
          If that email is registered, a reset link is on its way. Check your inbox.
        </div>
      ) : (
        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <label style={authLabelStyle}>
            <span style={authLabelTextStyle}>Email address</span>
            <input
              type="email"
              required
              placeholder="Enter your email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={authInputStyle}
            />
          </label>
          <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
            {submitting ? "Sending..." : "Send reset link"}
          </button>
        </form>
      )}

      {error && <div style={authErrorStyle}>{error}</div>}

      <p style={{ marginTop: 24, fontSize: 13, color: authColors.textMuted, textAlign: "center" }}>
        <Link to="/login" style={{ color: authColors.accentBlue }}>Back to sign in</Link>
      </p>
    </>
  );
}

export default function ForgotPassword() {
  return (
    <AuthLayout topRightPrompt="Remembered it?" topRightLabel="Sign in" topRightHref="/login">
      <ForgotPasswordForm />
    </AuthLayout>
  );
}
