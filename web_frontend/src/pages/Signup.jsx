import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  authInfoStyle,
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

function SignupForm() {
  const { isAuthenticated, loading, loginWithGoogleCode, signUpWithPassword } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
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
        setError(err.message || "Sign-up failed. Please try again.");
      } finally {
        setSubmitting(false);
      }
    },
    onError: () => {
      setError("Google sign-up was cancelled or failed. Please try again.");
    },
  });

  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setInfo("");
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
      await signUpWithPassword(email, password, displayName);
      navigate("/upload", { replace: true });
    } catch (err) {
      const msg = err.message || "Sign-up failed. Please try again.";
      if (msg.toLowerCase().startsWith("check your email")) {
        setInfo(msg);
      } else {
        setError(msg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 style={{ margin: "0 0 8px", fontSize: 40, fontWeight: 500, letterSpacing: "-0.025em", color: authColors.textPrimary }}>
        Create your account
      </h2>
      <p style={{ margin: "0 0 32px", fontSize: 15, lineHeight: 1.55, color: authColors.textSecondary }}>
        Start building your <span style={{ color: authColors.accentBlue }}>analysis workspace</span>.
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
            Sign up with Google
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
          <span style={authLabelTextStyle}>Full name</span>
          <input
            type="text"
            required
            placeholder="Ada Lovelace"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="sv-auth-input" style={authInputStyle}
          />
        </label>
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
          <span style={authLabelTextStyle}>Password</span>
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
          <span style={authLabelTextStyle}>Confirm password</span>
          <input
            type="password"
            required
            placeholder="Re-enter your password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className="sv-auth-input" style={authInputStyle}
          />
        </label>
        <button type="submit" disabled={submitting} style={{ ...authPrimaryButtonStyle, opacity: submitting ? 0.6 : 1 }}>
          {submitting ? "Creating account..." : "Create account"}
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M2 7h10M8 3l4 4-4 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>

      {info && <div style={authInfoStyle}>{info}</div>}
      {error && <div style={authErrorStyle}>{error}</div>}
    </>
  );
}

export default function Signup() {
  const content = (
    <AuthLayout topRightPrompt="Already have an account?" topRightLabel="Sign in" topRightHref="/login">
      <SignupForm />
    </AuthLayout>
  );

  if (!GOOGLE_CLIENT_ID) return content;
  return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{content}</GoogleOAuthProvider>;
}
