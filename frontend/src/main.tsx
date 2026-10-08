import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Landing from "./Landing";
import { useRoute } from "./router";
import "./styles.css";

function Root() {
  const route = useRoute();
  useEffect(() => {
    document.title = route === "app" ? "Workspace · Doorknock" : "Doorknock";
  }, [route]);
  return route === "app" ? <App /> : <Landing />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
