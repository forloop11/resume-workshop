import { existsSync, readdirSync, readFileSync } from "node:fs"
import { join, resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

// Styles the window is built with, which aren't among the modules bundled.
const STYLED_WITH = ["tailwindcss", "tw-animate-css", "shadcn", "@fontsource-variable/inter"]

/** Writes THIRD-PARTY-LICENSES.txt (Help > Third-Party Licenses): the license of each package that has code or styles in the built window. */
function licenses(): Plugin {
  return {
    name: "third-party-licenses",
    generateBundle() {
      const packages = new Set(STYLED_WITH)
      for (const id of this.getModuleIds()) {
        const match = /.*node_modules\/((?:@[^/]+\/)?[^/]+)\//.exec(id.replace(/\\/g, "/"))
        if (match) packages.add(match[1])
      }
      const rule = "=".repeat(78)
      const sections = [...packages].sort().flatMap((name) => {
        const folder = join(import.meta.dirname, "node_modules", name)
        if (!existsSync(join(folder, "package.json"))) return []
        const manifest = JSON.parse(readFileSync(join(folder, "package.json"), "utf8"))
        const texts = readdirSync(folder).filter((file) => /^(licen[sc]e|copying|notice)/i.test(file)).sort().map((file) => readFileSync(join(folder, file), "utf8").trim())
        const homepage = manifest.homepage ? `\nHomepage: ${manifest.homepage}` : ""
        return [`${rule}\n${name} ${manifest.version}\n${rule}\n\nLicense: ${manifest.license ?? "see below"}${homepage}\n\n${texts.join("\n\n")}\n`]
      })
      this.emitFile({ type: "asset", fileName: "THIRD-PARTY-LICENSES.txt", source: `The Resume Workshop window includes the software below, each under its own license.\n\n${sections.join("\n")}` })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), licenses()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/target/**"],
    },
  },
})
