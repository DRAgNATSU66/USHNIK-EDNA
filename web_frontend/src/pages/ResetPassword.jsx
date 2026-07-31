import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
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
        Choose a new password for your <span style={{ color: authColors.accentPurple }}>analysis workspace</span>.
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
            style={authInputStyle}
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
            style={authInputStyle}
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

export default function ResetPassword() {
  return (
    <AuthLayout topRightPrompt="Remembered it?" topRightLabel="Sign in" topRightHref="/login">
      <ResetPasswordForm />
    </AuthLayout>
  );
}
