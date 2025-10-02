// StakeholderDashboardPage.jsx
import React, { useState, useEffect } from "react";
import DashboardSelectionScreen from "./stakeholders/DashboardSelectionScreen";
import ResearcherDashboard from "./stakeholders/ResearcherDashboard";
import PolicymakerDashboard from "./stakeholders/PolicymakerDashboard";
import IndustryDashboard from "./stakeholders/IndustryDashboard";
import DashboardSwitcher from "./stakeholders/DashboardSwitcher";

export default function StakeholderDashboardPage() {
  const [currentView, setCurrentView] = useState("selection");

  // Always reset to selection on first mount (refresh)
  useEffect(() => {
    setCurrentView("selection");
  }, []);

  if (currentView === "selection") {
    return (
      <div className="min-h-screen bg-gray-950 text-white">
        <DashboardSelectionScreen onSelect={(id) => setCurrentView(id)} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <DashboardSwitcher
        currentDashboard={currentView}
        onSwitch={(id) => setCurrentView(id)}
        onBackToSelection={() => setCurrentView("selection")}
      />

      <div className="fade-container">
        {currentView === "researcher" && <ResearcherDashboard />}
        {currentView === "policymaker" && <PolicymakerDashboard />}
        {currentView === "industry" && <IndustryDashboard />}
      </div>
    </div>
  );
}
