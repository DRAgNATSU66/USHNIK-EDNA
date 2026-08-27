import PlaceholderScreen from "../components/PlaceholderScreen";
import NoveltyDNA from "./researcher/NoveltyDNA";
import SpeciesCorrection from "./researcher/SpeciesCorrection";
import FieldLog from "./researcher/FieldLog";

export default function ResearcherMode({ section }) {
  if (section === "novelty-dna") {
    return <NoveltyDNA />;
  }
  if (section === "species-correction") {
    return <SpeciesCorrection />;
  }
  if (section === "comments") {
    return <FieldLog />;
  }
  return <PlaceholderScreen title="Researcher Mode" description="This section isn't available yet." />;
}
