// The resume as the block editor edits it: input/resume.json (a JSON Resume
// document) and input/section_order.yaml, parsed. Edits change the parsed
// objects in place, so keys the editor doesn't know keep their place in the
// file. The rules a save is checked against are in Python
// (backend/document.py, through the backend's `problems`), whose reading of
// the two files this follows.
export type Entry = Record<string, any>
export type Group = Entry & { name: string; location: string; companyStack: string; roles: Entry[] }
export type Section = { id: string; label: string; list: string | null }

const ORDER_LINE = /^-\s+(\w+)(?:\s*:\s*(.*))?$/
const PAGEBREAK = "pagebreak"
export const ISO8601 = /^([1-2][0-9]{3}-[0-1][0-9]-[0-3][0-9]|[1-2][0-9]{3}-[0-1][0-9]|[1-2][0-9]{3})$/
export const BOLD = /\*\*(?=\S)(.+?)(?<=\S)\*\*/g
// Per-employer work[] fields the employer card edits for all of its roles.
export const EMPLOYER_KEYS = ["url", "description"]
const DEFAULT_ORDER_HEADER = [
  "# Resume sections, in the order they appear. Omit one to leave it out.",
  "# A `- pagebreak` line starts the next section on a new page.",
]

export const asList = (value: unknown): any[] => (Array.isArray(value) ? value : [])
const isObject = (value: unknown): value is Entry => typeof value === "object" && value !== null && !Array.isArray(value)
/** Resume text without its bold marks. */
export const plain = (text: string) => text.replace(BOLD, "$1")

export function parseOrder(text: string) {
  const header: string[] = []
  const sections: string[] = []
  const breaks = new Set<string>()
  const headings: Record<string, string> = {}
  let pendingBreak = false
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith("#")) {
      if (!sections.length && !pendingBreak) header.push(raw)
      continue
    }
    const match = ORDER_LINE.exec(line)
    if (!match) throw new Error(`section_order.yaml: can't read line "${raw}"`)
    if (match[1] === PAGEBREAK) {
      pendingBreak = true
      continue
    }
    sections.push(match[1])
    let heading = (match[2] ?? "").trim()
    if (heading.length > 1 && heading[0] === heading[heading.length - 1] && `"'`.includes(heading[0])) heading = heading.slice(1, -1)
    if (heading) headings[match[1]] = heading
    if (pendingBreak) breaks.add(match[1])
    pendingBreak = false
  }
  return { header, sections, breaks, headings }
}

/** Page breaks and headings are only written for sections in the resume. */
export function orderLines(sections: string[], breaks: Set<string>, headings: Record<string, string>) {
  const lines: string[] = []
  for (const section of sections) {
    if (breaks.has(section)) lines.push(`- ${PAGEBREAK}`)
    const heading = (headings[section] ?? "").trim()
    // Quoted where a bare "#" would start a comment, should YAML tools read the file.
    lines.push(`- ${section}` + (heading.includes("#") ? `: "${heading}"` : heading ? `: ${heading}` : ""))
  }
  return lines
}

/** work[] -> employer groups (consecutive entries with one name and location), and the earlyCareer entries. */
export function groupWork(work: unknown): { groups: Group[]; early: Entry[] } {
  const groups: Group[] = []
  const early: Entry[] = []
  for (const entry of asList(work)) {
    if (entry.earlyCareer) {
      early.push(entry)
      continue
    }
    const name = entry.name || ""
    const location = entry.location || ""
    const last = groups[groups.length - 1]
    if (last && last.name === name && last.location === location) last.roles.push(entry)
    else groups.push({ name, location, companyStack: "", roles: [entry] })
  }
  for (const group of groups) {
    group.companyStack = group.roles.find((role) => role.companyStack)?.companyStack ?? ""
    for (const key of EMPLOYER_KEYS) {
      const value = group.roles.find((role) => role[key])?.[key]
      if (value) group[key] = value
    }
  }
  return { groups, early }
}

/** The employer cards as flat work[] entries: each role gets its card's name and location, and companyStack lives on the first role only. */
export function flattenWork(groups: Group[], early: Entry[]) {
  const work: Entry[] = []
  for (const group of groups) {
    group.roles.forEach((role, i) => {
      role.name = group.name ?? ""
      if (group.location) role.location = group.location
      else delete role.location
      // Assign only on change, so existing keys keep their position in the file.
      const companyStack = i === 0 ? group.companyStack : ""
      if (!companyStack) delete role.companyStack
      else if (role.companyStack !== companyStack) role.companyStack = companyStack
      delete role.earlyCareer
      work.push(role)
    })
  }
  for (const entry of early) {
    entry.earlyCareer = true
    work.push(entry)
  }
  return work
}

/** A blank role; one added to `group` inherits the employer's website and description. */
export function newRole(group?: Group): Entry {
  const role: Entry = { name: "", position: "", highlights: [""] }
  for (const key of EMPLOYER_KEYS) if (group?.[key]) role[key] = group[key]
  return role
}

export class Doc {
  model: Entry
  groups: Group[]
  early: Entry[]
  order: string[]
  breaks: Set<string>
  headings: Record<string, string>
  orderHeader: string[]
  // Top-level arrays and objects shown before the document has them.
  detached: Record<string, any> = {}
  // The file text this document matches, as of the last parse or commit().
  parsedResume: string
  parsedOrder: string
  private lists: Record<string, string>

  /** Throws if either file can't be read as blocks. */
  constructor(resumeText: string, orderText: string, sections: Section[]) {
    const model = JSON.parse(resumeText)
    if (!isObject(model)) throw new Error("expected a JSON object")
    const order = parseOrder(orderText)
    this.order = order.sections
    this.breaks = order.breaks
    this.headings = order.headings
    this.orderHeader = order.header.length ? order.header : [...DEFAULT_ORDER_HEADER]
    this.model = model
    this.lists = Object.fromEntries(sections.filter((section) => section.list).map((section) => [section.id, section.list as string]))
    if (!isObject(model.basics)) model.basics = {}
    const entryLists: Record<string, unknown> = { work: model.work, "basics.profiles": model.basics.profiles }
    for (const key of Object.values(this.lists)) entryLists[key] = model[key]
    for (const [name, entries] of Object.entries(entryLists)) {
      if (!asList(entries).every(isObject)) throw new Error(`every ${name} entry must be a JSON object`)
    }
    const grouped = groupWork(model.work)
    this.groups = grouped.groups
    this.early = grouped.early
    this.parsedResume = resumeText
    this.parsedOrder = orderText
  }

  /** model[key] as a list (or object, for meta). A section the document doesn't have yet gets a stand-in that commit() adds to the model once it holds something. */
  topLevel(key: string, kind: "list" | "object" = "list") {
    const value = this.model[key]
    if (kind === "list" ? Array.isArray(value) : isObject(value)) return value
    return (this.detached[key] ??= kind === "list" ? [] : {})
  }

  listFor(section: string): Entry[] {
    return this.topLevel(this.lists[section])
  }

  included(section: string) {
    return this.order.includes(section)
  }

  /** Gives a section something to edit once it's added to the resume. */
  ensureSectionData(section: string) {
    const basics = this.model.basics
    if (section === "summary" && typeof basics.summary !== "string") basics.summary = ""
    const key = this.lists[section]
    if (key && !Array.isArray(this.model[key])) {
      this.model[key] = this.topLevel(key)
      delete this.detached[key]
    }
  }

  hasData(section: string) {
    if (section === "summary") return Boolean(this.model.basics.summary)
    if (section === "experience") return this.groups.length > 0
    if (section === "early_career") return this.early.length > 0
    return asList(this.model[this.lists[section]]).length > 0
  }

  /** Serializes the document after an edit. `orderText` is the order file's current text, kept as it is when only resume.json changed. */
  commit(orderText: string): [string, string] {
    for (const [key, value] of Object.entries(this.detached)) {
      if (Array.isArray(value) ? value.length : Object.keys(value).length) {
        this.model[key] = value
        delete this.detached[key]
      }
    }
    this.model.work = flattenWork(this.groups, this.early)
    const resumeText = JSON.stringify(this.model, null, 2)
    if (orderText !== this.parsedOrder || !this.sameOrder()) {
      orderText = [...this.orderHeader, ...orderLines(this.order, this.breaks, this.headings)].join("\n") + "\n"
    }
    this.parsedResume = resumeText
    this.parsedOrder = orderText
    return [resumeText, orderText]
  }

  private sameOrder() {
    try {
      const parsed = parseOrder(this.parsedOrder)
      return orderLines(parsed.sections, parsed.breaks, parsed.headings).join("\n") === orderLines(this.order, this.breaks, this.headings).join("\n")
    } catch {
      return false
    }
  }
}

// --- input/geometry.yaml, as Page Setup edits it ------------------------------------

export const GEOMETRY_FIELDS: [string, string][] = [
  ["top", "Top margin"],
  ["bottom", "Bottom margin"],
  ["left", "Left margin"],
  ["right", "Right margin"],
  ["footskip", "Footer distance"],
]
// TeX units: how many make an inch, and the decimal places worth showing.
export const UNITS: Record<string, [number, number]> = { in: [1, 2], cm: [2.54, 2], mm: [25.4, 1], pt: [72.27, 1] }
export const MAXIMUM_INCHES = 4 // more than that leaves no page
const GEOMETRY_LINE = /^(\s*)(\w+)(:\s*)(\S+)(.*)$/
export type Lengths = Record<string, [number, string]>

/** geometry.yaml -> {name: [number, unit]}. Throws for a required length that is missing or isn't a plain number and unit. */
export function parseGeometry(text: string): Lengths {
  const found: Record<string, string> = {}
  for (const line of text.split("\n")) {
    const match = GEOMETRY_LINE.exec(line)
    if (match && !line.trimStart().startsWith("#")) found[match[2]] = match[4]
  }
  const lengths: Lengths = {}
  for (const [name] of GEOMETRY_FIELDS) {
    const match = /^(\d*\.?\d+)([a-z]+)$/.exec(found[name] ?? "")
    if (!match || !(match[2] in UNITS)) throw new Error(name in found ? `${name}: ${found[name]}` : `${name} is missing`)
    lengths[name] = [parseFloat(match[1]), match[2]]
  }
  return lengths
}

/** geometry.yaml with `lengths` written in, its comments and other lines kept. */
export function updateGeometry(text: string, lengths: Lengths) {
  const values = Object.fromEntries(Object.entries(lengths).map(([name, [number, unit]]) => [name, number.toFixed(UNITS[unit][1]) + unit]))
  const lines = text.replace(/\n$/, "").split("\n").map((line) => {
    const match = GEOMETRY_LINE.exec(line)
    if (match && !line.trimStart().startsWith("#") && match[2] in values) {
      const value = values[match[2]]
      delete values[match[2]]
      return match[1] + match[2] + match[3] + value + match[5]
    }
    return line
  })
  for (const [name, value] of Object.entries(values)) lines.push(`${name}: ${value}`)
  return lines.join("\n") + "\n"
}
