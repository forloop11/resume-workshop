// Edit > Find and Replace: a bar under the tabs that searches the tab that
// is showing -- every field of the block editor, in order, or the raw
// resume.json. A match in a collapsed card opens the card. Replace types
// the replacement into the field, so the field's own undo reverses it.
import * as React from "react"

import { typeInto, type Report } from "@/components/blocks"
import { Button } from "@/components/ui/button"

type Field = HTMLInputElement | HTMLTextAreaElement
type Match = { field: Field; start: number; end: number }
export type FindHandle = { find(backward?: boolean): void }

const fieldLook = "w-56 rounded-md border border-input bg-[var(--rw-deep)] px-2 py-1 text-sm outline-none focus-visible:border-ring"

export const FindBar = React.forwardRef<FindHandle, {
  replacing: boolean
  /** The text boxes to look through: the showing tab's, in order. */
  targets(): Field[]
  report: Report
  onClose(): void
}>(function FindBar({ replacing, targets, report, onClose }, ref) {
  const [query, setQuery] = React.useState("")
  const [replacement, setReplacement] = React.useState("")
  const [matchCase, setMatchCase] = React.useState(false)
  const [wholeWords, setWholeWords] = React.useState(false)
  const [place, setPlace] = React.useState("")
  const input = React.useRef<HTMLInputElement>(null)
  const current = React.useRef<Match | null>(null)

  function scan(): Match[] {
    if (!query) return []
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    const pattern = new RegExp(wholeWords ? `(?<![\\p{L}\\p{N}_])${escaped}(?![\\p{L}\\p{N}_])` : escaped, matchCase ? "gu" : "giu")
    return targets().flatMap((field) => [...field.value.matchAll(pattern)].map((match) => ({ field, start: match.index, end: match.index + match[0].length })))
  }

  function mark(match: Match | null) {
    for (const marked of document.querySelectorAll("[data-find-current]")) marked.removeAttribute("data-find-current")
    current.current = match
    if (!match) return
    const { field, start, end } = match
    // Open the cards the field is folded away in.
    for (let node = field.parentElement; node; node = node.parentElement) {
      if (node.hidden) (node.previousElementSibling as HTMLElement | null)?.click()
    }
    field.setAttribute("data-find-current", "")
    field.setSelectionRange(start, end) // shown once the field has the focus: Esc puts it there
    if (field.scrollHeight > field.clientHeight + 4) {
      // A text box that scrolls, as the raw tab's does: bring the match's line to the middle.
      const line = parseFloat(getComputedStyle(field).lineHeight) || 20
      field.scrollTop = Math.max(field.value.slice(0, start).split("\n").length * line - field.clientHeight / 2, 0)
    }
    field.scrollIntoView({ block: "nearest" })
  }

  function find(backward = false) {
    const matches = scan()
    if (!matches.length) {
      mark(null)
      setPlace(query ? "No matches" : "")
      return
    }
    const fields = targets()
    const order = (match: Match) => fields.indexOf(match.field) * 1e9 + match.start
    const from = current.current && current.current.field.isConnected ? order(current.current) : backward ? Infinity : -1
    const next = backward ? [...matches].reverse().find((match) => order(match) < from) ?? matches[matches.length - 1]
      : matches.find((match) => order(match) > from) ?? matches[0]
    mark(next)
    setPlace(`${matches.indexOf(next) + 1} of ${matches.length}`)
  }

  /** Types the replacement over a match, leaving the cursor in the bar. */
  function put(match: Match) {
    typeInto(match.field, match.start, match.end, replacement)
    input.current?.focus()
  }

  function replace() {
    const match = current.current
    if (!match || !match.field.isConnected || match.field.value.slice(match.start, match.end).toLowerCase() !== query.toLowerCase()) return find()
    put(match)
    // On to the next one, from the end of what was just typed.
    current.current = { ...match, start: match.start + replacement.length - 1, end: match.start + replacement.length }
    find()
  }

  function replaceAll() {
    const matches = scan()
    for (const match of matches.reverse()) put(match) // from the end, so the places before stay put
    mark(null)
    setPlace("")
    report(matches.length ? `Replaced ${matches.length} match${matches.length === 1 ? "" : "es"}.` : "No matches to replace.", matches.length ? "ok" : "")
  }

  function close() {
    const match = current.current
    mark(null)
    onClose()
    if (match?.field.isConnected) {
      match.field.focus()
      match.field.setSelectionRange(match.start, match.end)
    }
  }

  React.useImperativeHandle(ref, () => ({ find }))
  React.useEffect(() => {
    input.current?.focus()
    input.current?.select()
    return () => mark(null)
  }, [])
  // The count follows the search as it is typed.
  React.useEffect(() => {
    current.current = null
    const matches = scan()
    mark(matches[0] ?? null)
    setPlace(matches.length ? `1 of ${matches.length}` : query ? "No matches" : "")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, matchCase, wholeWords])

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Enter") {
      event.preventDefault()
      find(event.shiftKey)
    } else if (event.key === "Escape") {
      event.preventDefault()
      close()
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 border-t border-border p-2 text-sm" data-find-bar onKeyDown={onKey}>
      <input ref={input} value={query} placeholder="Find" spellCheck={false} className={fieldLook} onChange={(event) => setQuery(event.target.value)} />
      <Button variant="outline" size="sm" title="Find previous (Shift+F3)" onClick={() => find(true)}>‹</Button>
      <Button variant="outline" size="sm" title="Find next (F3)" onClick={() => find()}>›</Button>
      <span className="min-w-20 text-xs text-muted-foreground" data-find-place>{place}</span>
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={matchCase} onChange={(event) => setMatchCase(event.target.checked)} /> Match case</label>
      <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={wholeWords} onChange={(event) => setWholeWords(event.target.checked)} /> Whole words</label>
      {replacing ? (<>
        <input value={replacement} placeholder="Replace with" spellCheck={false} className={fieldLook} onChange={(event) => setReplacement(event.target.value)} />
        <Button variant="outline" size="sm" onClick={replace}>Replace</Button>
        <Button variant="outline" size="sm" onClick={replaceAll}>Replace all</Button>
      </>) : null}
      <div className="flex-1" />
      <Button variant="ghost" size="sm" title="Close (Esc)" onClick={close}>✕</Button>
    </div>
  )
})
