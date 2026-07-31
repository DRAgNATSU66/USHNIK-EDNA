import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { authGoogleExchange, authMe, authSupabaseExchange } from "../lib/api";
import { supabase } from "../lib/supabaseClient";

const AuthContext = createContext(null);

const _loadUser = () => {
  try {
    const raw = localStorage.getItem("sv_user_profile");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

const _saveUser = (user) => {
  try {
    if (user) localStorage.setItem("sv_user_profile", JSON.stringify(user));
    else localStorage.removeItem("sv_user_profile");
  } catch {}
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => _loadUser());
  const [token, setToken] = useState(() => {
    try { return localStorage.getItem("sv_access_token"); } catch { return null; }
  });
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);

  const _persist = (tok, profile) => {
    try {
      localStorage.setItem("sv_access_token", tok);
    } catch {}
    _saveUser(profile);
    setToken(tok);
    setUser(profile);
    setAuthError(null);
  };

  const logout = useCallback(() => {
    try {
      localStorage.removeItem("sv_access_token");
      localStorage.removeItem("sv_user_profile");
    } catch {}
    setToken(null);
    setUser(null);
  }, []);

  /**
   * Exchange a Google ID token (from @react-oauth/google) for a Synth Veda JWT.
   * Stores the token and user profile in localStorage.
   */
  const loginWithGoogle = useCallback(async (googleIdToken) => {
    setAuthError(null);
    const data = await authGoogleExchange(googleIdToken);
    _persist(data.access_token, data.user);
    return data.user;
  }, []);

  const _exchangeSupabaseSession = useCallback(async (session) => {
    if (!session) {
      throw new Error("No active session. Please try again.");
    }
    const data = await authSupabaseExchange(session.access_token);
    _persist(data.access_token, data.user);
    return data.user;
  }, []);

  /**
   * Sign in with email + password via Supabase Auth, then exchange the
   * resulting session for a Synth Veda JWT.
   */
  const loginWithPassword = useCallback(async (email, password) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message);
    return _exchangeSupabaseSession(data.session);
  }, [_exchangeSupabaseSession]);

  /**
   * Create an account with email + password via Supabase Auth. Throws a
   * "check your email" message (not a hard failure) if the project ever
   * requires email confirmation and no session comes back.
   */
  const signUpWithPassword = useCallback(async (email, password, displayName) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: { data: { full_name: displayName } },
    });
    if (error) throw new Error(error.message);
    if (!data.session) {
      throw new Error("Check your email to confirm your account, then sign in.");
    }
    return _exchangeSupabaseSession(data.session);
  }, [_exchangeSupabaseSession]);

  /** Request a password-reset email via Supabase Auth. */
  const requestPasswordReset = useCallback(async (email) => {
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/reset-password`,
    });
    if (error) throw new Error(error.message);
  }, []);

  /**
   * Set a new password using the recovery session Supabase established
   * from the reset-link URL, then exchange it for a Synth Veda JWT.
   */
  const confirmPasswordReset = useCallback(async (newPassword) => {
    setAuthError(null);
    if (!supabase) {
      throw new Error("Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.");
    }
    const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
    if (updateError) throw new Error(updateError.message);
    const { data: sessionData } = await supabase.auth.getSession();
    if (!sessionData.session) {
      throw new Error("Reset link expired. Please request a new one.");
    }
    return _exchangeSupabaseSession(sessionData.session);
  }, [_exchangeSupabaseSession]);

  // On mount: if we have a stored token, verify it's still valid via GET /auth/me.
  // Use the stored user profile immediately so the UI isn't blocked on network.
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    authMe()
      .then((profile) => {
        _saveUser(profile);
        setUser(profile);
      })
      .catch(() => {
        // Token expired or invalid — clear session
        logout();
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const role = user?.role ?? null;
  const isAdmin = role === "admin";
  const isCurator = ["curator", "admin", "company_owner"].includes(role);
  const isExpeditionOp = ["expedition_operator", "admin", "company_owner"].includes(role);
  const isAuthenticated = !!user && !!token;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        authError,
        isAuthenticated,
        isAdmin,
        isCurator,
        isExpeditionOp,
        loginWithGoogle,
        loginWithPassword,
        signUpWithPassword,
        requestPasswordReset,
        confirmPasswordReset,
        logout,
        setAuthError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
