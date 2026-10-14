// The JSON Resume themes (Theme > JSON Resume Themes): packages from npm that
// turn a resume.json into a web page, each in its own look. They are the
// themes' own code, run in the window; the ones written for Node are given
// what they ask of it as the window is built (vite.config.ts).
import Handlebars from "handlebars"

type Module = { render(resume: unknown): string | Promise<string> }
export type JsonTheme = {
  id: string; name: string; about: string
  /** Whether it prints **bold** as bold; the others are given the text without the marks. */
  markdown?: boolean
  load(): Promise<Module>
}

export const JSON_THEMES: JsonTheme[] = [
  { id: "even", name: "Even", about: "Flat and modern, with a sidebar of dates", markdown: true, load: () => import("jsonresume-theme-even") },
  { id: "stackoverflow", name: "Stack Overflow", about: "After Stack Overflow's developer story", load: async () => (await import("virtual:json-theme/jsonresume-theme-stackoverflow")).default },
  { id: "engineering", name: "Engineering", about: "Plain and dense, in one column, for engineers", load: async () => (await import("virtual:json-theme/jsonresume-theme-engineering")).default },
  { id: "straightforward", name: "Straightforward", about: "One column, with little decoration", load: async () => (await import("virtual:json-theme/jsonresume-theme-straightforward")).default },
  { id: "paper", name: "Paper", about: "Like a printed page, with headings in the margin", load: async () => (await import("virtual:json-theme/jsonresume-theme-paper")).default },
]

// Several themes add helpers and partials of the same names to the one
// Handlebars there is, so each renders with those it added itself.
type Registered = { helpers: Record<string, unknown>; partials: Record<string, unknown> }
const handlebars = Handlebars as unknown as Registered
const registered = (): Registered => ({ helpers: { ...handlebars.helpers }, partials: { ...handlebars.partials } })
const builtIn = registered()
const loaded = new Map<string, { module: Module; own: Registered }>()
let turn: Promise<unknown> = Promise.resolve()

/** Text without the ** that marks bold, at every depth of a resume. */
function unmarked(value: unknown): unknown {
  if (typeof value === "string") return value.replaceAll("**", "")
  if (Array.isArray(value)) return value.map(unmarked)
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, inner]) => [key, unmarked(inner)]))
  return value
}

/** The resume (resume.json's text) as a web page in one of JSON_THEMES. One at a time: the themes share Handlebars. */
export function renderJsonTheme(id: string, resume: string): Promise<string> {
  const theme = JSON_THEMES.find((known) => known.id === id)
  if (!theme) return Promise.reject(new Error(`There is no JSON Resume theme called ${id}.`))
  const rendered = turn.then(async () => {
    const parsed = JSON.parse(resume) // a copy of its own: a theme may change what it is given
    let entry = loaded.get(id)
    Object.assign(handlebars, entry ? { helpers: { ...entry.own.helpers }, partials: { ...entry.own.partials } } : { helpers: { ...builtIn.helpers }, partials: { ...builtIn.partials } })
    if (!entry) {
      entry = { module: await theme.load(), own: registered() }
      loaded.set(id, entry)
    }
    return await entry.module.render(theme.markdown ? parsed : unmarked(parsed))
  })
  turn = rendered.catch(() => undefined)
  return rendered
}

/** A theme's page for showing inside the editor: without the stylesheets and scripts it would fetch or run (some themes ask for web fonts), and barred from the network. */
export function contained(html: string) {
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:">`
  const own = html.replace(/<link\b[^>]*>/gi, "").replace(/<script\b[\s\S]*?<\/script>/gi, "")
  return /<head[^>]*>/i.test(own) ? own.replace(/<head[^>]*>/i, (head) => head + policy) : policy + own
}
