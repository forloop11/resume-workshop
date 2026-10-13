// The drag-and-drop block editor for input/resume.json and
// input/section_order.yaml: a card for each section of a JSON Resume
// document, and a field for every property in its schema. Every edit re-serializes the document (lib/model.ts)
// into the window's file text, so the raw tab always shows the current
// blocks, and the other way round.
import * as React from "react"
import { ChevronDown, ChevronRight, GripVertical } from "lucide-react"

import { Button } from "@/components/ui/button"
import { openUrl, rpc } from "@/lib/bridge"
import { asList, Doc, EMPLOYER_KEYS, ISO8601, newRole, type Entry, type Group, type Section } from "@/lib/model"
import type { Miss, Speller } from "@/lib/spelling"
import { cn } from "@/lib/utils"

const UNDO_LIMIT = 50
const GRAMMAR_DELAY = 700 // ms after the last keystroke
// Fields that hold a web address, which get Test and Open buttons.
const LINKS = new Set(["url", "canonical"])
// Fields that hold identifiers rather than words, so aren't spell-checked.
const NOT_WORDS = new Set(["email", "phone", "url", "image", "username", "postalCode", "countryCode", "canonical", "version", "lastModified"])

export type Report = (message: string, kind?: string) => void
export type BlocksHandle = {
  /** What a save would be turned down for; highlights the fields at fault. */
  validate(): Promise<string[]>
  undo(): void
  canUndo(): boolean
  setAllOpen(open: boolean): void
  insertChar(char: string): void
  toggleBold(): void
  /** Checks grammar again, once what kept it off has been put right. */
  retryGrammar(): void
  duplicates(): number
}

/** A grammar problem in a field's text, from the backend's `grammar` (LanguageTool). */
type Problem = { start: number; end: number; message: string; replacements: string[]; rule: string }

type Context = {
  doc: Doc
  /** The misspelled words in `text`; none until the dictionary has loaded. */
  spell(text: string): Miss[]
  suggest(word: string): string[]
  /** Takes a word as spelled right: for good, in the folder's dictionary, or until the editor is closed. */
  addWord(word: string, keep: boolean): void
  /** The grammar problems in `text` that haven't been dismissed; none while grammar checking is off. */
  grammar(text: string): Promise<Problem[]>
  ignore(rule: string, flagged: string): void
  /** After typing in a field: writes the document back to the files. */
  edit(): void
  /** A change to the document's shape, which Undo reverses. */
  change(mutate: () => void): void
  report: Report
  showInvalid: boolean
  isOpen(key: object | string, byDefault: boolean): boolean
  setOpen(key: object | string, open: boolean): void
  focused(element: HTMLInputElement | HTMLTextAreaElement): void
}
const BlocksContext = React.createContext<Context>(null as unknown as Context)
const useBlocks = () => React.useContext(BlocksContext)

/** Types `text` over part of a field, as the keyboard would, so the field's own undo reverses it. */
export function typeInto(field: HTMLInputElement | HTMLTextAreaElement, start: number, end: number, text: string) {
  field.focus()
  field.setSelectionRange(start, end)
  document.execCommand("insertText", false, text)
}

// --- dragging ----------------------------------------------------------------------

// What is being dragged: the list it is in, where, and which lists may take it.
let dragging: { group: string; list: any[]; index: number } | null = null

type Move = (source: any[], from: number, target: any[], to: number) => void

/** A list whose items can be dragged by their handles, to another place in it or into another list of the same `group`. */
function Sortable<T>({ items, group, onMove, render, className, flow }: {
  items: T[]; group: string; onMove: Move; render: (item: T, index: number, handle: React.ReactNode) => React.ReactNode; className?: string; flow?: boolean
}) {
  const [over, setOver] = React.useState<number | null>(null)
  const accepts = () => dragging !== null && dragging.group === group

  function drop(to: number) {
    const source = dragging
    dragging = null
    setOver(null)
    if (!source) return
    // Taking the item out first moves the places after it up by one.
    if (source.list === items && source.index < to) to -= 1
    if (source.list !== items || source.index !== to) onMove(source.list, source.index, items, to)
  }

  return (
    <div
      className={cn(flow ? "flex flex-wrap gap-1.5" : "flex flex-col gap-2", className)}
      onDragOver={(event) => {
        if (accepts()) event.preventDefault()
      }}
      onDrop={(event) => {
        if (!accepts()) return
        event.preventDefault()
        drop(items.length) // dropped past the last item, or into an empty list
      }}
    >
      {items.map((item, index) => {
        const handle = (
          <span
            draggable
            title="Drag to reorder"
            className="cursor-grab text-muted-foreground hover:text-foreground"
            onDragStart={(event) => {
              dragging = { group, list: items, index }
              event.dataTransfer.effectAllowed = "move"
              event.dataTransfer.setData("text/plain", "")
              const card = (event.currentTarget as HTMLElement).closest("[data-sortable-item]")
              if (card) event.dataTransfer.setDragImage(card, 12, 12)
              event.stopPropagation()
            }}
            onDragEnd={() => {
              dragging = null
              setOver(null)
            }}
          >
            <GripVertical className="size-4" />
          </span>
        )
        return (
          <div
            key={index}
            data-sortable-item
            className={cn("min-w-0", over === index && "outline outline-2 outline-offset-2 outline-primary")}
            onDragOver={(event) => {
              if (!accepts()) return
              event.preventDefault()
              event.stopPropagation()
              setOver(index)
            }}
            onDragLeave={() => setOver((current) => (current === index ? null : current))}
            onDrop={(event) => {
              if (!accepts()) return
              event.preventDefault()
              event.stopPropagation()
              const box = event.currentTarget.getBoundingClientRect()
              const after = flow ? event.clientX > box.left + box.width / 2 : event.clientY > box.top + box.height / 2
              drop(index + (after ? 1 : 0))
            }}
          >
            {render(item, index, handle)}
          </div>
        )
      })}
    </div>
  )
}

// --- fields ------------------------------------------------------------------------

type FieldOptions = {
  multiline?: boolean; required?: boolean; date?: boolean; placeholder?: string; hint?: string; onInput?: () => void
  /** A list of strings, one per line. */
  lines?: boolean
  /** Shown in place of the label and its field's own key. */
  bare?: boolean
}

function FieldLabel({ text, required, hint }: { text: string; required?: boolean; hint?: string }) {
  return (
    <div className="mb-0.5 text-xs text-muted-foreground">
      <span className="text-foreground/90">{text}</span>
      {required ? <span className="text-[var(--rw-hover)]"> *</span> : null}
      {hint ? <span> — {hint}</span> : null}
    </div>
  )
}

/** An auto-growing text box bound to obj[key]: one line, unless `multiline`. An emptied field removes its key, as JSON Resume documents usually omit unused fields, except required ones, which stay as "". */
function Field({ obj, k, label, ...options }: { obj: Entry; k: string | number; label: string } & FieldOptions) {
  const blocks = useBlocks()
  const { multiline, required, date, lines, hint } = options
  const stored = obj[k]
  const fromModel = lines ? asList(stored).map(String).join("\n") : stored == null ? "" : String(stored)
  // A list field shows what was typed (blank lines and all) until it is left.
  const [typed, setTyped] = React.useState<string | null>(null)
  const value = typed ?? fromModel
  const invalid = blocks.showInvalid && ((required && !value.trim()) || (date && value !== "" && !ISO8601.test(value)))
  const [tested, setTested] = React.useState("")
  const [here, setHere] = React.useState(false) // the cursor is in this field
  const area = React.useRef<HTMLTextAreaElement>(null)
  // Spelling is checked where there are words; grammar where there are sentences: the summaries, descriptions, and highlights.
  const words = !date && !NOT_WORDS.has(String(k))
  const proofed = Boolean(multiline) && !lines
  const misses = words ? blocks.spell(value) : []
  const [found, setFound] = React.useState<{ text: string; problems: Problem[] }>({ text: "", problems: [] })
  React.useEffect(() => {
    if (!proofed || !value.trim()) return
    let current = true
    const timer = window.setTimeout(() => blocks.grammar(value).then((problems) => current && setFound({ text: value, problems })), GRAMMAR_DELAY)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proofed, value, blocks.grammar])
  const problems = found.text === value ? found.problems : []

  function changed(text: string) {
    if (lines) {
      setTyped(text)
      const items = text.split("\n").map((line) => line.trim()).filter(Boolean)
      if (!items.length && !required) delete obj[k]
      else obj[k] = items
    } else {
      if (!multiline) text = text.replace(/\n/g, " ") // pasted, say: this field is one line
      if (text === "" && !required && typeof k === "string") delete obj[k]
      else obj[k] = text
    }
    blocks.edit()
    options.onInput?.()
  }

  // The text with its problems marked, for the copy of it under the text box: spelling, and grammar where the two don't overlap.
  const marks = [...misses.map((miss) => ({ ...miss, kind: "spelling", title: "Not in the dictionary" })), ...problems.map((problem) => ({ ...problem, kind: "grammar", title: problem.message }))]
    .sort((one, other) => one.start - other.start || (one.kind === "spelling" ? -1 : 1))
  const marked: React.ReactNode[] = []
  let at = 0
  for (const mark of marks) {
    if (mark.start < at) continue
    marked.push(value.slice(at, mark.start), <mark key={mark.start} data-kind={mark.kind} title={mark.title}>{value.slice(mark.start, mark.end)}</mark>)
    at = mark.end
  }
  marked.push(value.slice(at) + " ")
  const put = (start: number, end: number, text: string) => area.current && typeInto(area.current, start, end, text)

  const control = (
    // The text box grows with its text: a copy of the text under it sets the height of both, and
    // shows through it, with the spelling and grammar problems underlined.
    <div className="min-w-0 flex-1">
      <div className="grow-wrap">
        <div className="grow-mirror" aria-hidden>{marked}</div>
        <textarea
          ref={area} value={value} rows={lines ? 2 : 1} spellCheck={false}
          placeholder={options.placeholder || (date ? "YYYY-MM" : undefined)}
          aria-invalid={invalid || undefined} data-field="" data-required={required ? "" : undefined} data-date={date ? "" : undefined}
          className="resize-none overflow-hidden outline-none select-text placeholder:text-muted-foreground/70"
          onChange={(event) => changed(event.target.value)}
          // The preview's highlight follows the text as it is typed.
          onInput={(event) => blocks.focused(event.currentTarget)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !multiline && !lines) event.preventDefault()
          }}
          onFocus={(event) => {
            setHere(true)
            blocks.focused(event.currentTarget)
          }}
          onBlur={() => {
            setHere(false)
            setTyped(null)
          }}
        />
      </div>
      {here && (misses.length || problems.length) ? (
        // onMouseDown: keep the cursor in the field
        <div className="mt-1 flex flex-col gap-1 text-xs" data-proofing onMouseDown={(event) => event.preventDefault()}>
          {misses.map((miss) => (
            <div key={`s${miss.start}`} className="flex flex-wrap items-center gap-1" data-spelling>
              <span className="text-destructive">“{miss.word}”</span>
              <span className="text-muted-foreground">isn't in the dictionary.</span>
              {blocks.suggest(miss.word).map((suggestion) => (
                <Button key={suggestion} variant="outline" size="xs" onClick={() => put(miss.start, miss.end, suggestion)}>{suggestion}</Button>
              ))}
              <Button variant="ghost" size="xs" title="Add to this resume folder's etc/dictionary.txt" onClick={() => blocks.addWord(miss.word, true)}>Add to dictionary</Button>
              <Button variant="ghost" size="xs" title="Until the editor is closed" onClick={() => blocks.addWord(miss.word, false)}>Ignore</Button>
            </div>
          ))}
          {problems.map((problem) => (
            <div key={`g${problem.start}`} className="flex flex-wrap items-center gap-1" data-grammar>
              <span className="text-[var(--rw-warning)]">“{value.slice(problem.start, problem.end)}”</span>
              <span className="text-muted-foreground">{problem.message}</span>
              {problem.replacements.map((replacement) => (
                <Button key={replacement} variant="outline" size="xs" onClick={() => put(problem.start, problem.end, replacement)}>{replacement}</Button>
              ))}
              <Button
                variant="ghost" size="xs" title="Until the editor is closed"
                onClick={() => {
                  blocks.ignore(problem.rule, value.slice(problem.start, problem.end))
                  setFound({ text: value, problems: problems.filter((other) => other !== problem) })
                }}
              >
                Ignore
              </Button>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )

  return (
    <div className="min-w-0 flex-1">
      {options.bare ? null : <FieldLabel text={label} required={required} hint={hint} />}
      {LINKS.has(String(k)) ? (
        <div className="flex gap-1">
          {control}
          <Button
            variant="outline" size="sm" title="Check that this address works"
            onClick={async () => {
              if (!value.trim()) return blocks.report("There's no address here yet.", "error")
              setTested("…")
              blocks.report(`Testing ${value.trim()}…`)
              const result = await rpc("test_link", { url: value }).catch(() => null)
              setTested(result ? { ok: "✓ ", error: "✗ " }[result.state as string] ?? "? " : "")
              if (result) blocks.report(result.message, result.state)
            }}
          >
            {tested === "…" ? "…" : `${tested}Test`}
          </Button>
          <Button
            variant="outline" size="sm" title="Open this address in your browser"
            onClick={async () => {
              if (!value.trim()) return blocks.report("There's no address here yet.", "error")
              const url = value.includes("://") ? value.trim() : `https://${value.trim()}`
              if (!/^https?:\/\/[^\s/]+\.[^\s]+$/.test(url)) return blocks.report("That isn't a web address to open or test.", "error")
              await openUrl(url)
            }}
          >
            Open
          </Button>
        </div>
      ) : control}
    </div>
  )
}

const Row = ({ children }: { children: React.ReactNode }) => <div className="flex items-start gap-2">{children}</div>

function Dates({ obj, placeholder, endPlaceholder, hint }: { obj: Entry; placeholder?: string; endPlaceholder?: string; hint?: string }) {
  return (
    <Row>
      <Field obj={obj} k="startDate" label="Start" date placeholder={placeholder} hint={hint} />
      <Field obj={obj} k="endDate" label="End" date placeholder={endPlaceholder || placeholder} hint={hint} />
    </Row>
  )
}

/** The less usual fields, folded away; open if any of `keys` is filled in. */
function More({ of, keys, children }: { of: Entry[]; keys: string[]; children: React.ReactNode }) {
  const filled = of.some((obj) => keys.some((key) => (Array.isArray(obj[key]) ? obj[key].length : obj[key])))
  const [open, setOpen] = React.useState(filled)
  return (
    <div className="rounded-md border border-dashed border-border">
      <button type="button" className="flex w-full items-center gap-1 px-2 py-1 text-xs text-muted-foreground" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />} More fields
      </button>
      <div hidden={!open} className="flex flex-col gap-2 px-2.5 pb-2">{children}</div>
    </div>
  )
}

function PageToggle({ on, set }: { on: boolean; set: (on: boolean) => void }) {
  const blocks = useBlocks()
  return (
    <Button
      variant={on ? "default" : "outline"} size="xs"
      title={on ? "Starts on a new page (click to undo)" : "Start on a new page"}
      onClick={(event) => {
        event.stopPropagation()
        blocks.change(() => set(!on))
      }}
    >
      New page
    </Button>
  )
}

function EntryPageToggle({ entry }: { entry: Entry }) {
  return (
    <PageToggle
      on={Boolean(entry.pagebreakBefore)}
      set={(on) => {
        if (on) entry.pagebreakBefore = true
        else delete entry.pagebreakBefore
      }}
    />
  )
}

function ItemTools({ items, index, duplicate = true, pagebreak }: { items: any[]; index: number; duplicate?: boolean; pagebreak?: React.ReactNode }) {
  const blocks = useBlocks()
  return (
    <div className="flex shrink-0 items-center gap-1" onClick={(event) => event.stopPropagation()}>
      {pagebreak}
      {duplicate ? (
        <Button variant="outline" size="xs" onClick={() => blocks.change(() => items.splice(index + 1, 0, structuredClone(items[index])))}>Duplicate</Button>
      ) : null}
      <Button variant="destructive" size="xs" onClick={() => blocks.change(() => items.splice(index, 1))}>Delete</Button>
    </div>
  )
}

const AddButton = ({ label, add }: { label: string; add: () => void }) => {
  const blocks = useBlocks()
  return <Button variant="outline" size="sm" className="self-start" onClick={() => blocks.change(add)}>{label}</Button>
}

/** A card for each of a list's simple entries: a drag handle, its fields, and Duplicate and Delete. */
function EntryList({ items, group, fields, addLabel, blank, pagebreak = true }: {
  items: Entry[]; group: string; fields: (item: Entry, index: number) => React.ReactNode; addLabel: string; blank: () => Entry; pagebreak?: boolean
}) {
  const blocks = useBlocks()
  return (
    <div className="flex flex-col gap-2">
      <Sortable
        items={items} group={group} onMove={(source, from, target, to) => blocks.change(() => target.splice(to, 0, source.splice(from, 1)[0]))}
        render={(item, index, handle) => (
          <div className="flex items-start gap-2 rounded-lg border border-border bg-[var(--rw-bar)] p-2.5">
            <div className="pt-5">{handle}</div>
            <div className="flex min-w-0 flex-1 flex-col gap-2">{fields(item, index)}</div>
            <ItemTools items={items} index={index} pagebreak={pagebreak ? <EntryPageToggle entry={item} /> : undefined} />
          </div>
        )}
      />
      <AddButton label={addLabel} add={() => items.push(blank())} />
    </div>
  )
}

/** A collapsible card, remembering whether the user left it open. */
function Card({ id, title, tag, warning, openByDefault, tools, excluded, children }: {
  id: object | string; title: React.ReactNode; tag?: string | null; warning?: string | null; openByDefault: boolean; tools?: React.ReactNode
  excluded?: boolean; children: React.ReactNode
}) {
  const blocks = useBlocks()
  const open = blocks.isOpen(id, openByDefault)
  return (
    <section className={cn("rounded-xl border border-border bg-card", excluded && "opacity-70")}>
      <header className="flex cursor-pointer items-center gap-2 px-3.5 py-2.5" onClick={() => blocks.setOpen(id, !open)}>
        {open ? <ChevronDown className="size-4 shrink-0" /> : <ChevronRight className="size-4 shrink-0" />}
        <div className="min-w-0 truncate font-semibold">{title}</div>
        {tag ? <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">{tag}</span> : null}
        {warning ? <span className="shrink-0 rounded-full bg-[var(--rw-warning)] px-2 py-0.5 text-xs text-primary-foreground">{warning}</span> : null}
        <div className="flex-1" />
        {tools}
      </header>
      <div hidden={!open} className="flex flex-col gap-2.5 px-3.5 pb-3.5">{children}</div>
    </section>
  )
}

// --- the cards ---------------------------------------------------------------------

function Basics() {
  const { doc } = useBlocks()
  const basics = doc.model.basics
  if (typeof basics.location !== "object" || basics.location === null || Array.isArray(basics.location)) basics.location = {}
  if (!Array.isArray(basics.profiles)) basics.profiles = []
  const location = basics.location
  return (
    <Card id="basics" title="Header" tag="basics" openByDefault>
      <Row>
        <Field obj={basics} k="name" label="Name" required />
        <Field obj={basics} k="label" label="Title" required />
        <Field obj={basics} k="email" label="Email" required />
      </Row>
      <Row>
        <Field obj={basics} k="phone" label="Phone" required />
        <Field obj={location} k="city" label="City" required />
        <Field obj={location} k="region" label="Region / state" />
      </Row>
      <Field obj={basics} k="url" label="Website" placeholder="https://" hint="printed before the profile links" />
      <More of={[location, basics]} keys={["address", "postalCode", "countryCode", "image"]}>
        <Row>
          <Field obj={location} k="address" label="Street address" />
          <Field obj={location} k="postalCode" label="Postal code" />
        </Row>
        <Row>
          <Field obj={location} k="countryCode" label="Country code" placeholder="US" />
          <Field obj={basics} k="image" label="Photo" placeholder="input/photo.png" hint="an image file in the resume folder" />
        </Row>
      </More>
      <FieldLabel text="Profile links" hint="printed in this order" />
      <EntryList
        items={basics.profiles} group="profiles" addLabel="+ Add profile link" blank={() => ({ network: "", url: "" })} pagebreak={false}
        fields={(profile) => (
          <div className="flex items-start gap-2">
            <div className="flex-[2]"><Field obj={profile} k="network" label="Network" placeholder="LinkedIn" /></div>
            <div className="flex-[2]"><Field obj={profile} k="username" label="Username" hint="link text ends here" /></div>
            <div className="flex-[5]"><Field obj={profile} k="url" label="URL" required placeholder="https://" /></div>
          </div>
        )}
      />
    </Card>
  )
}

function Meta() {
  const { doc } = useBlocks()
  const meta = doc.topLevel("meta", "object")
  return (
    <Card id="meta" title="Document info" tag="meta · printed at the foot of the last page" openByDefault={false}>
      <Row>
        <Field obj={meta} k="canonical" label="Canonical URL" placeholder="https://" hint="where this resume.json is published" />
        <Field obj={meta} k="version" label="Version" placeholder="v1.0.0" />
        <Field obj={meta} k="lastModified" label="Last modified" placeholder="2026-10-06T12:00:00" />
      </Row>
    </Card>
  )
}

function SectionOrder({ sections }: { sections: Section[] }) {
  const blocks = useBlocks()
  const { doc } = blocks
  const labels = Object.fromEntries(sections.map((section) => [section.id, section.label]))
  const excluded = sections.map((section) => section.id).filter((id) => !doc.order.includes(id))

  const moved: Move = (source, from, target, to) => {
    if (source === excluded && target === excluded) return // the left-out sections have no order of their own
    blocks.change(() => {
      target.splice(to, 0, source.splice(from, 1)[0])
      for (const section of doc.order) doc.ensureSectionData(section)
    })
  }

  const chips = (list: string[], included: boolean) => (
    <Sortable
      items={list} group="section-order" onMove={moved} flow
      className={cn("min-h-11 rounded-lg border border-border p-1.5", included ? "bg-[var(--rw-deep)]" : "border-dashed opacity-80")}
      render={(section, _index, handle) => (
        <div className="flex items-center gap-1.5 rounded-full border border-border bg-card py-1 pr-3 pl-2 text-sm">
          {handle}
          <span>{included ? doc.headings[section] || labels[section] || section : labels[section] || section}</span>
          {included && doc.breaks.has(section) ? <span className="text-xs text-[var(--rw-warning)]" title="Starts on a new page">new page</span> : null}
        </div>
      )}
    />
  )

  return (
    <section className="flex flex-col gap-2 rounded-xl border border-border bg-card px-3.5 py-3">
      <div className="font-semibold">Sections</div>
      <div className="text-xs text-muted-foreground">Drag to reorder. Drag a section to the second row to leave it out of the resume (its content is kept).</div>
      {chips(doc.order, true)}
      {chips(excluded, false)}
    </section>
  )
}

/** For each Core Competencies entry, what it repeats: a name another has, or a keyword listed elsewhere (backend/document.py's competency_duplicates). */
export function competencyDuplicates(skills: Entry[]): string[][] {
  const key = (text: unknown) => String(text).toLowerCase().split(/\s+/).filter(Boolean).join(" ")
  const names = new Map<string, number[]>()
  const keywords = new Map<string, number[]>()
  const note = (map: Map<string, number[]>, name: string, index: number) => map.set(name, [...(map.get(name) ?? []), index])
  skills.forEach((skill, i) => {
    note(names, key(skill.name || ""), i)
    for (const keyword of asList(skill.keywords)) note(keywords, key(keyword), i)
  })
  return skills.map((skill, i) => {
    const messages: string[] = []
    const name = key(skill.name || "")
    if (name && (names.get(name)?.length ?? 0) > 1) messages.push("another competency has this name")
    // The first spelling of each keyword, so "Docker" and "docker " are reported once.
    const spellings = new Map<string, string>()
    for (const keyword of [...asList(skill.keywords)].reverse()) spellings.set(key(keyword), String(keyword).trim())
    for (const keyword of spellings.values()) {
      const places = keywords.get(key(keyword)) ?? []
      if (!keyword || places.length < 2) continue
      const others = [...new Set(places)].filter((j) => j !== i).map((j) => skills[j].name || `competency #${j + 1}`)
      messages.push(others.length ? `“${keyword}” is also in ${others.join(", ")}` : `“${keyword}” is listed twice`)
    }
    return messages
  })
}

function Role({ role, index, group, handle }: { role: Entry; index: number; group: Group; handle: React.ReactNode }) {
  const blocks = useBlocks()
  if (!Array.isArray(role.highlights)) role.highlights = []
  const highlights: string[] = role.highlights
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-[var(--rw-bar)] p-2.5">
      <div className="flex items-center gap-2.5">
        {handle}
        <div className="text-sm font-semibold text-[var(--rw-link)]">Role</div>
        <div className="flex-1" />
        {/* The first role's page break is the employer card's toggle. */}
        <ItemTools items={group.roles} index={index} pagebreak={index ? <EntryPageToggle entry={role} /> : undefined} />
      </div>
      <Row>
        <Field obj={role} k="position" label="Position" required />
        <Field obj={role} k="startDate" label="Start" date />
        <Field obj={role} k="endDate" label="End" date placeholder="Present" />
      </Row>
      <Field obj={role} k="summary" label="Summary" multiline hint="printed above the highlights" />
      <FieldLabel text="Highlights" hint="the role's bullet points; a role needs highlights or a summary" />
      <Sortable
        items={highlights} group="highlights" className="gap-1" onMove={(source, from, target, to) => blocks.change(() => target.splice(to, 0, source.splice(from, 1)[0]))}
        render={(_text, i, grip) => (
          <div className="flex items-start gap-1.5">
            <div className="pt-1.5">{grip}</div>
            <Field obj={highlights} k={i} label="Highlight" bare multiline required />
            <Button variant="destructive" size="icon-sm" title="Delete highlight" onClick={() => blocks.change(() => highlights.splice(i, 1))}>✕</Button>
          </div>
        )}
      />
      <AddButton label="+ Add highlight" add={() => highlights.push("")} />
      <Field obj={role} k="stack" label="Stack" hint="printed under this role" />
    </div>
  )
}

function Employer({ group, index, handle }: { group: Group; index: number; handle: React.ReactNode }) {
  const blocks = useBlocks()
  const { doc } = blocks
  const roles = group.roles
  const title = [group.name || "(new employer)", group.location, `${roles.length} role${roles.length === 1 ? "" : "s"}`].filter(Boolean).join(" · ")
  // JSON Resume keeps employer fields on each work[] entry; set them on all of the employer's roles.
  const copyToRoles = (key: string) => {
    for (const role of roles) {
      if (group[key]) role[key] = group[key]
      else delete role[key]
    }
    blocks.edit()
  }
  return (
    <Card
      id={group} openByDefault={false}
      title={<span className="flex items-center gap-2"><span onClick={(event) => event.stopPropagation()}>{handle}</span>{title}</span>}
      tools={<ItemTools items={doc.groups} index={index} pagebreak={roles.length ? <EntryPageToggle entry={roles[0]} /> : undefined} />}
    >
      <Row>
        <Field obj={group} k="name" label="Employer" required />
        <Field obj={group} k="location" label="Location" />
      </Row>
      <Field obj={group} k="companyStack" label="Company stack" hint="printed once, after all roles" />
      <More of={[group]} keys={EMPLOYER_KEYS}>
        <Field obj={group} k="url" label="Employer website" placeholder="https://" hint="makes the name a link" onInput={() => copyToRoles("url")} />
        <Field obj={group} k="description" label="Employer description" placeholder="Construction equipment manufacturer" hint="printed under the name" onInput={() => copyToRoles("description")} />
      </More>
      <Sortable
        items={roles} group="roles" className="gap-2.5" onMove={(source, from, target, to) => blocks.change(() => target.splice(to, 0, source.splice(from, 1)[0]))}
        render={(role, i, grip) => <Role role={role} index={i} group={group} handle={grip} />}
      />
      <AddButton label="+ Add role" add={() => roles.push(newRole(group))} />
    </Card>
  )
}

function Experience() {
  const blocks = useBlocks()
  const groups = blocks.doc.groups
  return (
    <div className="flex flex-col gap-2">
      <Sortable
        items={groups} group="employers" onMove={(source, from, target, to) => blocks.change(() => target.splice(to, 0, source.splice(from, 1)[0]))}
        render={(group, index, handle) => <Employer group={group} index={index} handle={handle} />}
      />
      <AddButton
        label="+ Add employer"
        add={() => {
          const group: Group = { name: "", location: "", companyStack: "", roles: [newRole()] }
          groups.unshift(group)
          blocks.setOpen(group, true)
        }}
      />
    </div>
  )
}

function SectionBody({ id, duplicates }: { id: string; duplicates: string[][] }) {
  const { doc } = useBlocks()
  const list = (section: string) => doc.listFor(section)
  switch (id) {
    case "summary":
      return <Field obj={doc.model.basics} k="summary" label="basics.summary" multiline required={doc.included(id)} />
    case "experience":
      return <Experience />
    case "early_career":
      return (
        <EntryList
          items={doc.early} group="early" addLabel="+ Add early career entry" blank={() => ({ name: "", position: "", earlyCareer: true })}
          fields={(e) => (<>
            <Row><Field obj={e} k="position" label="Position" required /><Field obj={e} k="name" label="Employer(s)" required /></Row>
            <Dates obj={e} placeholder="YYYY" hint="printed as years" />
            <Field obj={e} k="summary" label="Summary" multiline hint="printed after the dates" />
            <More of={[e]} keys={["location", "url", "description", "highlights"]}>
              <Row><Field obj={e} k="location" label="Location" /><Field obj={e} k="url" label="Employer website" placeholder="https://" hint="makes the name a link" /></Row>
              <Field obj={e} k="description" label="Employer description" />
              <Field obj={e} k="highlights" label="Highlights" lines hint="one per line, printed after the summary" />
            </More>
          </>)}
        />
      )
    case "volunteer":
      return (
        <EntryList
          items={list(id)} group="volunteer" addLabel="+ Add volunteer role" blank={() => ({ organization: "", position: "" })}
          fields={(v) => (<>
            <Row><Field obj={v} k="organization" label="Organization" required /><Field obj={v} k="position" label="Position" required /></Row>
            <Dates obj={v} endPlaceholder="Present" />
            <Field obj={v} k="summary" label="Summary" multiline hint="printed above the highlights" />
            <Field obj={v} k="highlights" label="Highlights" lines hint="one per line, printed as bullets" />
            <More of={[v]} keys={["url"]}><Field obj={v} k="url" label="Website" placeholder="https://" hint="makes the organization a link" /></More>
          </>)}
        />
      )
    case "competencies":
      return (
        <EntryList
          items={list(id)} group="skills" addLabel="+ Add competency" blank={() => ({ name: "", keywords: [] })}
          fields={(s, index) => (<>
            <Row><Field obj={s} k="name" label="Name" required /><Field obj={s} k="level" label="Level" placeholder="Advanced" hint="printed after the name" /></Row>
            <Field obj={s} k="keywords" label="Keywords" lines required hint="one per line, printed separated by ·" />
            {duplicates[index]?.length ? <div className="text-xs text-[var(--rw-warning)]">Duplicate: {duplicates[index].join("; ")}.</div> : null}
          </>)}
        />
      )
    case "education":
      return (
        <EntryList
          items={list(id)} group="education" addLabel="+ Add education" blank={() => ({ institution: "", studyType: "" })}
          fields={(e) => (<>
            <Row><Field obj={e} k="studyType" label="Degree type" placeholder="Bachelor of Science" /><Field obj={e} k="area" label="Area" hint="printed as “type in area”" /></Row>
            <Row><Field obj={e} k="institution" label="Institution" required /><Field obj={e} k="score" label="Score" placeholder="3.8 GPA" hint="printed after the institution" /></Row>
            <Dates obj={e} placeholder="YYYY" hint="printed as years" />
            <Field obj={e} k="courses" label="Courses" lines hint="one per line, printed under the entry" />
            <More of={[e]} keys={["url"]}><Field obj={e} k="url" label="Institution website" placeholder="https://" hint="makes the institution a link" /></More>
          </>)}
        />
      )
    case "certifications":
      return (
        <EntryList
          items={list(id)} group="certificates" addLabel="+ Add certification" blank={() => ({ name: "" })}
          fields={(c) => (<>
            <Row><Field obj={c} k="name" label="Name" required /><Field obj={c} k="issuer" label="Issuer" hint="printed after the name" /></Row>
            <More of={[c]} keys={["date", "url"]}>
              <Row><Field obj={c} k="date" label="Date" date hint="printed as the year" /><Field obj={c} k="url" label="URL" placeholder="https://" hint="makes the name a link" /></Row>
            </More>
          </>)}
        />
      )
    case "recognition":
      return (
        <EntryList
          items={list(id)} group="awards" addLabel="+ Add entry" blank={() => ({ title: "" })}
          fields={(a) => (<>
            <Field obj={a} k="title" label="Title" required />
            <Field obj={a} k="summary" label="Summary" multiline />
            <More of={[a]} keys={["date", "awarder"]}>
              <Row><Field obj={a} k="date" label="Date" date placeholder="YYYY" hint="printed unless the title has the year" /><Field obj={a} k="awarder" label="Awarder" hint="printed unless the title names it" /></Row>
            </More>
          </>)}
        />
      )
    case "publications":
      return (
        <EntryList
          items={list(id)} group="publications" addLabel="+ Add publication" blank={() => ({ name: "" })}
          fields={(p) => (<>
            <Row><Field obj={p} k="name" label="Title" required /><Field obj={p} k="publisher" label="Publisher" hint="printed after the title" /></Row>
            <Field obj={p} k="releaseDate" label="Release date" date hint="printed as the year" />
            <Field obj={p} k="summary" label="Summary" multiline />
            <More of={[p]} keys={["url"]}><Field obj={p} k="url" label="URL" placeholder="https://" hint="makes the title a link" /></More>
          </>)}
        />
      )
    case "projects":
      return (
        <EntryList
          items={list(id)} group="projects" addLabel="+ Add project" blank={() => ({ name: "" })}
          fields={(p) => (<>
            <Field obj={p} k="name" label="Name" required />
            <Field obj={p} k="description" label="Description" multiline />
            <Field obj={p} k="highlights" label="Highlights" lines hint="one per line, printed as bullets" />
            <Field obj={p} k="keywords" label="Keywords" lines hint="one per line, printed as a Stack line" />
            <More of={[p]} keys={["startDate", "endDate", "url", "entity", "type", "roles"]}>
              <Dates obj={p} endPlaceholder="Present" />
              <Row>
                <Field obj={p} k="url" label="URL" placeholder="https://" hint="makes the name a link" />
                <Field obj={p} k="entity" label="Entity" placeholder="Company or organization" />
                <Field obj={p} k="type" label="Type" placeholder="application" />
              </Row>
              <Field obj={p} k="roles" label="Your roles" lines hint="one per line, printed after the name" />
            </More>
          </>)}
        />
      )
    case "languages":
      return (
        <EntryList
          items={list(id)} group="languages" addLabel="+ Add language" blank={() => ({ language: "" })}
          fields={(l) => <Row><Field obj={l} k="language" label="Language" required /><Field obj={l} k="fluency" label="Fluency" placeholder="Native speaker" hint="printed after the language" /></Row>}
        />
      )
    case "interests":
      return (
        <EntryList
          items={list(id)} group="interests" addLabel="+ Add interest" blank={() => ({ name: "" })}
          fields={(i) => (<><Field obj={i} k="name" label="Name" required /><Field obj={i} k="keywords" label="Keywords" lines hint="one per line, printed separated by ·" /></>)}
        />
      )
    case "references":
      return (
        <EntryList
          items={list(id)} group="references" addLabel="+ Add reference" blank={() => ({ name: "", reference: "" })}
          fields={(r) => (<><Field obj={r} k="name" label="Name" required /><Field obj={r} k="reference" label="Reference" multiline required /></>)}
        />
      )
    default:
      return <div className="text-sm text-muted-foreground">Edit “{id}” in the raw resume.json tab.</div>
  }
}

/** Every section gets a card, so any part of the schema can be filled in; ones left out of the resume start collapsed unless they hold something. */
function SectionCard({ section, duplicates }: { section: Section; duplicates: string[][] }) {
  const { doc } = useBlocks()
  const id = section.id
  const included = doc.included(id)
  const hasData = doc.hasData(id)
  const count = id === "competencies" ? duplicates.reduce((sum, messages) => sum + messages.length, 0) : 0
  return (
    <Card
      id={id} title={included ? doc.headings[id] || section.label : section.label} excluded={!included} openByDefault={included || hasData}
      tag={!included ? "not in resume" : id !== "summary" && !hasData ? "empty · not printed" : null}
      warning={count ? `${count} duplicate${count === 1 ? "" : "s"}` : null}
      tools={included ? <PageToggle on={doc.breaks.has(id)} set={(on) => (on ? doc.breaks.add(id) : doc.breaks.delete(id))} /> : undefined}
    >
      {included ? <Field obj={doc.headings} k={id} label="Heading" placeholder={section.label} hint="printed in place of the usual one; empty for that" /> : null}
      <SectionBody id={id} duplicates={duplicates} />
    </Card>
  )
}

// --- the editor --------------------------------------------------------------------

type Props = {
  resume: string
  order: string
  sections: Section[]
  /** The document after an edit, as the two files' text. */
  onChange(resume: string, order: string): void
  report: Report
  /** The text of the field the cursor has moved into, for the preview to highlight. */
  onFocusText(text: string): void
  /** The resume folder's own spelling list (etc/dictionary.txt). */
  words: string[]
  /** Adds a word to that list. */
  onAddWord(word: string): void
  /** What is going on in the background ("" for nothing), to show beside the window's title. */
  onActivity(text: string): void
}

export const Blocks = React.forwardRef<BlocksHandle, Props>(function Blocks({ resume, order, sections, onChange, report, onFocusText, words, onAddWord, onActivity }, ref) {
  const [, redraw] = React.useReducer((count: number) => count + 1, 0)
  const [showInvalid, setShowInvalid] = React.useState(false)
  const state = React.useRef({
    doc: null as Doc | null, error: "", undo: [] as [string, string][],
    open: new Map<object | string, boolean>(), lastField: null as HTMLInputElement | HTMLTextAreaElement | null,
    // Grammar: what has been checked, what is waiting to be, what was dismissed, and whether checking is off.
    checked: new Map<string, Problem[]>(), asking: new Map<string, ((problems: Problem[]) => void)[]>(), ignored: new Set<string>(), grammarOff: false,
  }).current

  /** Asks the backend about the texts waiting, all in one request. */
  const askGrammar = React.useCallback(async () => {
    const asking = new Map(state.asking)
    state.asking.clear()
    // LanguageTool takes several seconds to start, and minutes the first time, as it is downloaded.
    const slow = state.checked.size ? 0 : window.setTimeout(() => onActivity("Starting the grammar checker…"), 2000)
    const answer = await rpc("grammar", { texts: [...asking.keys()] }).catch((error) => ({ off: String(error.message ?? error), missing: false, results: {} }))
    window.clearTimeout(slow)
    if (slow) onActivity("")
    if (answer.off && !state.grammarOff) {
      state.grammarOff = true
      // Missing the optional grammar checker isn't an error; anything else is.
      report(`Grammar checking is off: ${answer.off}`, answer.missing ? "" : "error")
    }
    for (const [text, waiting] of asking) {
      const problems: Problem[] = answer.results[text] ?? []
      if (text in answer.results) state.checked.set(text, problems)
      for (const resolve of waiting) resolve(problems)
    }
  }, [state, report, onActivity])

  const grammar = React.useCallback((text: string) => {
    const shown = (problems: Problem[]) => problems.filter((problem) => !state.ignored.has(`${problem.rule}\u0000${text.slice(problem.start, problem.end)}`))
    const known = state.checked.get(text)
    if (known || state.grammarOff) return Promise.resolve(shown(known ?? []))
    return new Promise<Problem[]>((resolve) => {
      if (!state.asking.size) window.setTimeout(askGrammar, 50) // the fields ask together as a resume opens
      state.asking.set(text, [...(state.asking.get(text) ?? []), (problems) => resolve(shown(problems))])
    })
  }, [state, askGrammar])
  const container = React.useRef<HTMLDivElement>(null)

  // The spelling checker, loaded once the window is up (its dictionary is large), and again for another folder's words.
  const [speller, setSpeller] = React.useState<Speller | null>(null)
  const spelled = React.useRef(new Map<string, Miss[]>()).current
  React.useEffect(() => {
    let current = true
    const timer = window.setTimeout(() => {
      import("@/lib/spelling").then(({ Speller }) => {
        if (!current) return
        spelled.clear()
        setSpeller(new Speller(words))
      })
    }, 300)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [words, spelled])

  // Picks up edits made elsewhere (the raw tab, a reload, an import).
  if (!state.doc || state.doc.parsedResume !== resume || state.doc.parsedOrder !== order) {
    const openEmployers = state.doc ? state.doc.groups.map((group) => state.open.get(group) === true) : []
    try {
      state.doc = new Doc(resume, order, sections)
      state.error = ""
      // Parsing makes new objects, so which employers were open is carried over by position.
      state.doc.groups.forEach((group, i) => openEmployers[i] && state.open.set(group, true))
    } catch (error) {
      state.doc = null
      state.error = String((error as Error).message ?? error)
    }
  }
  const doc = state.doc

  const commit = () => {
    if (!state.doc) return
    const [resumeText, orderText] = state.doc.commit(order)
    onChange(resumeText, orderText)
    redraw()
  }

  const context: Context | null = doc && {
    doc, report, showInvalid, grammar,
    spell(text) {
      if (!speller || !text) return []
      let misses = spelled.get(text)
      if (!misses) spelled.set(text, (misses = speller.check(text)))
      return misses
    },
    suggest: (word) => speller?.suggest(word) ?? [],
    addWord(word, keep) {
      speller?.add(word)
      spelled.clear()
      if (keep) onAddWord(word)
      redraw()
    },
    ignore: (rule, flagged) => void state.ignored.add(`${rule}\u0000${flagged}`),
    edit: commit,
    change(mutate) {
      state.undo.push([doc.parsedResume, doc.parsedOrder])
      if (state.undo.length > UNDO_LIMIT) state.undo.shift()
      mutate()
      commit()
    },
    isOpen: (key, byDefault) => state.open.get(key) ?? byDefault,
    setOpen(key, open) {
      state.open.set(key, open)
      redraw()
    },
    focused(element) {
      state.lastField = element
      onFocusText(element.value)
    },
  }

  React.useImperativeHandle(ref, () => ({
    async validate() {
      if (!doc) return [`resume.json can't be shown as blocks: ${state.error}`]
      let anyInvalid = false
      let badDates = 0
      for (const field of container.current?.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("[data-field]") ?? []) {
        if (field.dataset.required !== undefined && !field.value.trim()) anyInvalid = true
        if (field.dataset.date !== undefined && field.value && !ISO8601.test(field.value)) {
          badDates += 1
          anyInvalid = true
        }
      }
      const problems: string[] = (await rpc("problems", { resume, order })).problems
      if (badDates) problems.push(`${badDates} date${badDates === 1 ? " is" : "s are"} not YYYY, YYYY-MM, or YYYY-MM-DD.`)
      if (!problems.length && anyInvalid) problems.push("Fill in the highlighted required fields.")
      setShowInvalid(problems.length > 0)
      return problems
    },
    undo() {
      const snapshot = state.undo.pop()
      if (snapshot) onChange(snapshot[0], snapshot[1])
    },
    canUndo: () => state.undo.length > 0,
    setAllOpen(open) {
      if (!doc) return
      for (const key of ["basics", "meta", ...sections.map((section) => section.id), ...doc.groups]) state.open.set(key, open)
      redraw()
    },
    insertChar(char) {
      const field = state.lastField
      if (!field?.isConnected) return report("Click into a field first, then insert.")
      typeInto(field, field.selectionStart ?? field.value.length, field.selectionEnd ?? field.value.length, char)
    },
    toggleBold() {
      const field = state.lastField
      if (!field?.isConnected) return report("Click into a field first, then make words bold.")
      const text = field.value
      let start = field.selectionStart ?? 0
      let end = field.selectionEnd ?? 0
      if (start === end) {
        // No selection: the word the cursor is in.
        while (start > 0 && /[^\s*]/.test(text[start - 1])) start -= 1
        while (end < text.length && /[^\s*]/.test(text[end])) end += 1
      }
      const selected = text.slice(start, end)
      if (!selected.trim() || selected.includes("\n")) return report("Select the words to make bold, within one line.")
      if (text.slice(start - 2, start) === "**" && text.slice(end, end + 2) === "**") typeInto(field, start - 2, end + 2, selected)
      else if (selected.length > 4 && selected.startsWith("**") && selected.endsWith("**")) typeInto(field, start, end, selected.slice(2, -2))
      else {
        // The marks go around the words, inside any space selected with them.
        const [, before, words, after] = /^(\s*)(.*?)(\s*)$/.exec(selected)!
        typeInto(field, start, end, `${before}**${words}**${after}`)
      }
    },
    retryGrammar() {
      state.grammarOff = false
      state.checked.clear()
      redraw()
    },
    duplicates: () => (doc ? competencyDuplicates(doc.listFor("competencies")).reduce((sum, messages) => sum + messages.length, 0) : 0),
  }))

  if (!doc || !context) {
    return (
      <div className="p-6 text-sm">
        <div className="font-semibold text-destructive">resume.json can't be shown as blocks.</div>
        <div className="mt-1 text-muted-foreground">{state.error}</div>
        <div className="mt-1 text-muted-foreground">Fix it in the resume.json tab, or reload the files from disk.</div>
      </div>
    )
  }

  const duplicates = competencyDuplicates(doc.listFor("competencies"))
  const ordered = [...doc.order.map((id) => sections.find((section) => section.id === id)).filter(Boolean), ...sections.filter((section) => !doc.order.includes(section.id))] as Section[]
  return (
    <BlocksContext.Provider value={context}>
      <div ref={container} className="flex flex-col gap-3.5 p-4">
        <Basics />
        <SectionOrder sections={sections} />
        {ordered.map((section) => <SectionCard key={section.id} section={section} duplicates={duplicates} />)}
        <Meta />
      </div>
    </BlocksContext.Provider>
  )
})
