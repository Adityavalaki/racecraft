import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { FeatureWindow } from "./FeatureWindow";
import { featureById } from "./features";
import "./styles.css";

// The same page serves the replay window and every feature window: one opened
// as /?feature=strategy&session=2024_01_R shows that feature, following the
// replay window's clock; anything else is the replay itself.
const params = new URLSearchParams(window.location.search);
const feature = featureById(params.get("feature"));
const session = params.get("session");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {feature && session ? <FeatureWindow feature={feature} initialSession={session} /> : <App />}
  </StrictMode>,
);
