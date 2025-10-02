// web_frontend/src/main.jsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import App from "./App"; // Analytics page (Page 2)
import Landing from "./pages/Landing"; // Landing page (Page 1)
import Admin from "./pages/Admin"; // Admin page (Page 3 - curation)
import StakeholderDashboardPage from "./pages/StakeholderDashboardPage"; // Stakeholder page (selected from Analytics)
import "./index.css";

// NOTE: If you haven't yet created StakeholderDashboardPage.jsx, keep the file import
// and create that component later in src/pages. The dev server will show an error
// until that component exists. If you'd rather avoid the import error now, temporarily
// comment the import and the corresponding Route line.

function RootRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Landing */}
        <Route path="/" element={<Landing />} />

        {/* Analytics (Page 2) */}
        <Route path="/analytics" element={<App />} />

        {/* Admin (Page 3 option A) */}
        <Route path="/admin" element={<Admin />} />

        {/* Stakeholder (Page 3 option B) - two-state page (selection / dashboard) */}
        <Route path="/stakeholder" element={<StakeholderDashboardPage />} />

        {/* helpful shortcuts */}
        <Route path="/home" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element not found. Make sure there is a <div id='root'></div> in index.html");
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <RootRoutes />
  </React.StrictMode>
);
