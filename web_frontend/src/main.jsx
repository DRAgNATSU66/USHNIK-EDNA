import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";

// Pages
import Login from "./pages/Login";
import Signup from "./pages/Signup";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Dashboard from "./pages/Dashboard";
import Upload from "./pages/Upload";
import JobProgress from "./pages/JobProgress";
import AnalysisResults from "./pages/AnalysisResults";
import ReviewQueue from "./pages/ReviewQueue";
import Admin from "./pages/Admin";
import ModelStatus from "./pages/ModelStatus";
import AbyssSetup from "./pages/AbyssSetup";

import "./index.css";

const isCurator = (role) =>
  ["curator", "admin", "company_owner"].includes(role);

const isAdmin = (role) =>
  role === "admin";

function AppRoutes() {
  return (
    <Routes>
      {/* Public */}
      <Route path="/" element={<Login />} />
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />

      {/* Protected: any authenticated user */}
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route
        path="/upload"
        element={
          <ProtectedRoute>
            <Upload />
          </ProtectedRoute>
        }
      />
      <Route
        path="/jobs/:job_id"
        element={
          <ProtectedRoute>
            <JobProgress />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analysis/:analysis_id"
        element={
          <ProtectedRoute>
            <AnalysisResults />
          </ProtectedRoute>
        }
      />
      <Route
        path="/models"
        element={
          <ProtectedRoute>
            <ModelStatus />
          </ProtectedRoute>
        }
      />
      <Route
        path="/abyss"
        element={
          <ProtectedRoute>
            <AbyssSetup />
          </ProtectedRoute>
        }
      />

      {/* Protected: curator/admin only */}
      <Route
        path="/reviews"
        element={
          <ProtectedRoute requiredRole={isCurator}>
            <ReviewQueue />
          </ProtectedRoute>
        }
      />

      {/* Protected: admin only (component also guards internally) */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute requiredRole={isAdmin}>
            <Admin />
          </ProtectedRoute>
        }
      />

      {/* Redirects */}
      <Route path="/home" element={<Navigate to="/" replace />} />
      <Route path="/analytics" element={<Navigate to="/upload" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element not found. Ensure index.html has <div id='root'></div>.");
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>
);
