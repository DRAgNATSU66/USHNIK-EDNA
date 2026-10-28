import Academia from "./partner/Academia";
import Legislative from "./partner/Legislative";
import Industrial from "./partner/Industrial";

export default function PartnerReport({ sector }) {
  if (sector === "academia") {
    return <Academia />;
  }
  if (sector === "legislative") {
    return <Legislative />;
  }
  return <Industrial />;
}
