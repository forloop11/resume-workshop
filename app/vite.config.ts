import { existsSync, readdirSync, readFileSync } from "node:fs"
import { join, relative, resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, type Plugin } from "vite"

// Styles the window is built with, which aren't among the modules bundled.
const STYLED_WITH = ["tailwindcss", "tw-animate-css", "shadcn", "@fontsource-variable/inter"]

// The JSON Resume themes (src/lib/json-themes.ts) that are written for Node:
// CommonJS, reading their templates and styles from their own folder.
const NODE_THEMES = ["jsonresume-theme-engineering", "jsonresume-theme-paper", "jsonresume-theme-stackoverflow", "jsonresume-theme-straightforward"]
const THEME_FILES = /\.(hbs|css|template)$/
// Node's own modules, as much of them as those themes use, over the files of the theme (FILES, a folder's path -> text).
const NODE = `
const normal = (path) => {
  const parts = []
  for (const part of path.split("/")) part === ".." ? parts.pop() : part && part !== "." && parts.push(part)
  return "/" + parts.join("/")
}
const path = {
  join: (...parts) => normal(parts.join("/")), resolve: (...parts) => normal(parts.join("/")), dirname: (file) => normal(file + "/.."),
  extname: (file) => /(\\.[^./]*)?$/.exec(file)[0], basename: (file, ending = "") => { const name = file.split("/").pop(); return ending && name.endsWith(ending) ? name.slice(0, -ending.length) : name },
}
const within = (folder) => Object.keys(FILES).filter((file) => file.startsWith(normal(folder) + "/"))
const fs = {
  readFileSync(file) { const text = FILES[normal(String(file))]; if (text === undefined) throw new Error("No such file in the theme: " + file); return text },
  readdirSync: (folder) => [...new Set(within(folder).map((file) => file.slice(normal(folder).length + 1).split("/")[0]))],
  existsSync: (file) => normal(String(file)) in FILES || within(file).length > 0,
}
const NODE = { fs, path, url: {} }
`

/** One of NODE_THEMES as a module the window can load ("virtual:json-theme/<package>"): the theme's own code, given the files it reads and the Node modules it asks for. */
function nodeThemes(): Plugin {
  const prefix = "virtual:json-theme/"
  const files = (folder: string): string[] => readdirSync(folder, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? (["node_modules", "docs", "test"].includes(entry.name) ? [] : files(join(folder, entry.name))) : THEME_FILES.test(entry.name) ? [join(folder, entry.name)] : [])
  return {
    name: "json-resume-node-themes",
    resolveId: (id) => (id.startsWith(prefix) ? `\0${id}` : null),
    load(id) {
      if (!id.startsWith(`\0${prefix}`)) return null
      const name = id.slice(prefix.length + 1)
      if (!NODE_THEMES.includes(name)) throw new Error(`${name} isn't one of the themes in vite.config.ts.`)
      const folder = join(import.meta.dirname, "node_modules", name)
      const manifest = JSON.parse(readFileSync(join(folder, "package.json"), "utf8"))
      const entry = join(folder, manifest.main ?? "index.js")
      const code = readFileSync(entry, "utf8")
      const within = (file: string) => `/${relative(folder, file).replace(/\\/g, "/")}`
      const texts = Object.fromEntries(files(folder).map((file) => [within(file), readFileSync(file, "utf8")]))
      // What it asks for besides Node's own: packages, which are bundled in as any other.
      const packages = [...new Set([...code.matchAll(/\brequire\(\s*["']([^"'.][^"']*)["']\s*\)/g)].map((match) => match[1]))].filter((asked) => !["fs", "path", "url"].includes(asked))
      return [
        ...packages.map((asked, index) => `import package${index} from ${JSON.stringify(asked)}`),
        `const FILES = ${JSON.stringify(texts)}`,
        NODE,
        `const PACKAGES = {${packages.map((asked, index) => `${JSON.stringify(asked)}: package${index}`).join(", ")}}`,
        "const module = { exports: {} }",
        `;(function (module, exports, require, __dirname, __filename) {\n${code}\n})(module, module.exports, (asked) => NODE[asked] ?? PACKAGES[asked], ${JSON.stringify(within(join(entry, "..")).replace(/^\/$/, "") || "/")}, ${JSON.stringify(within(entry))})`,
        "export default module.exports",
      ].join("\n")
    },
  }
}

/** Writes THIRD-PARTY-LICENSES.txt (Help > Third-Party Licenses): the license of each package that has code or styles in the built window. */
function licenses(): Plugin {
  return {
    name: "third-party-licenses",
    generateBundle() {
      const packages = new Set([...STYLED_WITH, ...NODE_THEMES])
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
  plugins: [react(), tailwindcss(), nodeThemes(), licenses()],
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
