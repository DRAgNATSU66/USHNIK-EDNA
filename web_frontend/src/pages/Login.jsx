import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { GoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authDividerStyle,
  authErrorStyle,
} from "../components/auth/authStyles";

const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || "";

function LoginForm() {
  const { loginWithGoogle, loginWithPassword } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleGoogleSuccess = async (credentialResponse) => {
    setSubmitting(true);
    setError("");
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-in failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleError = () => {
    setError("Google sign-in was cancelled or failed. Please try again.");
  };

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await loginWithPassword(email, password);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-in failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Welcome back
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Sign in to access your <span style={{ color: authColors.accentBlue }}>analysis workspace</span>.
      </p>

      {GOOGLE_CLIENT_ID && (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, marginBottom: 24 }}>
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
            theme="outline"
            shape="pill"
            size="large"
            text="continue_with"
            width={400}
          />
          <div style={authDividerStyle}>
            <span style={{ flex: 1, height: 1, background: authColors.dividerLine }} />
            OR
            <span style={{ flex: 1, height: 1, background: authColors.dividerLine }} />
          </div>
        </div>
      )}

      <form onSubmit={handlePasswordSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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
        <label style={authLabelStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={authLabelTextStyle}>Password</span>
            <Link to="/forgot-password" style={{ fontSize: "12.5px", color: authColors.accentBlue }}>
              Forgot password?
            </Link>
          </div>
          <input
            type="password"
            required
            placeholder="Enter your password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Signing in..." : "Sign in"}
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>

      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

export default function Login() {
  const content = (
    <AuthLayout topRightPrompt="New to Synth Veda?" topRightLabel="Create account" topRightHref="/signup">
      <LoginForm />
    </AuthLayout>
  );

  if (!GOOGLE_CLIENT_ID) return content;
  return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{content}</GoogleOAuthProvider>;
}
