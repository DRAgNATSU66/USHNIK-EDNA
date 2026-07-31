import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  authInfoStyle,
} from "../components/auth/authStyles";

const GOOGLE_CLIENT_ID = import.meta.env?.VITE_GOOGLE_CLIENT_ID || "";

function SignupForm() {
  const { isAuthenticated, loading, loginWithGoogle, signUpWithPassword } = useAuth();
  const navigate = useNavigate();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  useEffect(() => {
    if (!loading && isAuthenticated) navigate("/dashboard", { replace: true });
  }, [isAuthenticated, loading, navigate]);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleGoogleSuccess = async (credentialResponse) => {
    setSubmitting(true);
    setError("");
    try {
      await loginWithGoogle(credentialResponse.credential);
      navigate("/dashboard", { replace: true });
    } catch (err) {
      setError(err.message || "Sign-up failed. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleGoogleError = () => {
    setError("Google sign-up was cancelled or failed. Please try again.");
  };

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
      navigate("/dashboard", { replace: true });
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
          <GoogleLogin
            onSuccess={handleGoogleSuccess}
            onError={handleGoogleError}
            theme="filled_black"
            shape="pill"
            size="large"
            text="signup_with"
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
