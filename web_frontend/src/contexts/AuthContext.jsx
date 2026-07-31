import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { authGoogleExchange, authMe } from "../lib/api";

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
