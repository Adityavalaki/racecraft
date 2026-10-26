import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { FeatureWindow } from "./FeatureWindow";
import { featureById } from "./features";
// The fonts ship with the app, so the desktop build looks the same offline.
import "@fontsource/titillium-web/400.css";
import "@fontsource/titillium-web/600.css";
import "@fontsource/titillium-web/700.css";
import "@fontsource/barlow-condensed/600-italic.css";
import "@fontsource/barlow-condensed/700-italic.css";
import "@fontsource/barlow-condensed/800-italic.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/600.css";
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
