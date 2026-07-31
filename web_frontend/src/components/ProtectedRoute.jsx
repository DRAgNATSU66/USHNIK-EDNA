import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

/**
 * Wraps a route so it requires authentication.
 * Optional `requiredRole` prop accepts a function (role) => boolean for
 * fine-grained role checks.
 */
export default function ProtectedRoute({ children, requiredRole }) {
  const { isAuthenticated, loading, user } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        height: "100vh", background: "#001133", color: "#00d4ff", fontSize: 18,
      }}>
        Loading...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/" state={{ from: location }} replace />;
  }

  if (requiredRole && !requiredRole(user?.role)) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
}
