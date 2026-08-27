import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useGoogleLogin, GoogleOAuthProvider } from "@react-oauth/google";
import { useAuth } from "../contexts/AuthContext";
import AuthLayout from "../components/auth/AuthLayout";
import {
  authColors,
  authInputStyle,
  authLabelStyle,
  authLabelTextStyle,
  authPrimaryButtonStyle,
  authGoogleButtonStyle,
  authDividerStyle,
  authErrorStyle,
} from "../components/auth/authStyles";

const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || "";

function GoogleGlyph() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

function LoginForm() {
  const { isAuthenticated, loading, loginWithGoogleCode, loginWithPassword } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && isAuthenticated) navigate("/upload", { replace: true });
  }, [isAuthenticated, loading, navigate]);

  const googleLogin = useGoogleLogin({
    flow: "auth-code",
    onSuccess: async (codeResponse) => {
      setSubmitting(true);
      setError("");
      try {
        await loginWithGoogleCode(codeResponse.code);
        navigate("/upload", { replace: true });
      } catch (err) {
        setError(err.message || "Sign-in failed. Please try again.");
      } finally {
        setSubmitting(false);
      }
    },
    onError: () => {
      setError("Google sign-in was cancelled or failed. Please try again.");
    },
  });

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await loginWithPassword(email, password);
      navigate("/upload", { replace: true });
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
          <button
            type="button"
            onClick={() => googleLogin()}
            disabled={submitting}
            style={{ ...authGoogleButtonStyle, opacity: submitting ? 0.6 : 1 }}
          >
            <GoogleGlyph />
            Continue with Google
          </button>
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
            className="sv-auth-input" style={authInputStyle}
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
            className="sv-auth-input" style={authInputStyle}
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
