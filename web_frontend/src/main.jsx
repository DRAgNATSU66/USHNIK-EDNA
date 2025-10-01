// web_frontend/src/main.jsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";

import App from "./App";                // Analytics page
import Landing from "./pages/Landing";  // Landing page
import Admin from "./pages/Admin";      // Admin page (make sure this file exists in src/pages)
import DetailedAnalysis from "./pages/DetailedAnalysis"; // Detailed Analysis page
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/analytics" element={<App />} />
        <Route path="/admin" element={<Admin />} /> {/* Admin route added */}
        <Route path="/detailed-analysis" element={<DetailedAnalysis />} /> {/* Detailed Analysis route */}
        {/* future routes:
            <Route path="/history" element={<History />} />
        */}
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
