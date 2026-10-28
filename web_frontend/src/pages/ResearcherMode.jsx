import { Navigate, useLocation } from "react-router-dom";
import NoveltyDNA from "./researcher/NoveltyDNA";
import SpeciesCorrection from "./researcher/SpeciesCorrection";
import FieldLog from "./researcher/FieldLog";

const SECTIONS = {
  "novelty-dna": NoveltyDNA,
  "species-correction": SpeciesCorrection,
  comments: FieldLog,
};

const DEFAULT_SECTION = "novelty-dna";

export default function ResearcherMode({ section }) {
  const { search } = useLocation();
  const Section = SECTIONS[section];
  if (Section) return <Section />;
  // Unknown or missing section (/researcher-mode, /researcher-mode/whatever):
  // send the user to a real page rather than a "coming soon" placeholder.
  // The query string is kept so ?analysis_id= survives the redirect.
  return <Navigate to={`/researcher-mode/${DEFAULT_SECTION}${search}`} replace />;
}
