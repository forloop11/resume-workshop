import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import "./index.css"
import App from "./App.tsx"
import { ExternalLinkGuard } from "./components/external-link-guard.tsx"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ExternalLinkGuard />
    <main className="h-full"><App /></main>
  </StrictMode>
)
