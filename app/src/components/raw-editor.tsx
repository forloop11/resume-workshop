// The raw resume.json tab's text box, with the JSON object keys colored. A
// text box can't color its own text, so the colored text is drawn under it,
// in step with it, and the box's own text is left clear.
import * as React from "react"

const KEY = /"(?:[^"\\]|\\.)*"(?=\s*:)/g

export function RawEditor({ value, wrap, onChange }: { value: string; wrap: boolean; onChange(text: string): void }) {
  const under = React.useRef<HTMLPreElement>(null)
  const colored: React.ReactNode[] = []
  let at = 0
  for (const match of value.matchAll(KEY)) {
    colored.push(value.slice(at, match.index), <span key={match.index} className="font-semibold text-[var(--rw-link)]">{match[0]}</span>)
    at = match.index + match[0].length
  }
  colored.push(value.slice(at) + "\n")
  // Both layers: the same type, the same space around it, and room kept for the scroll bars, so the lines break alike.
  const layer = "absolute inset-0 m-0 overflow-auto p-4 font-mono text-sm leading-5 [scrollbar-gutter:stable] [tab-size:2] "
    + (wrap ? "whitespace-pre-wrap [overflow-wrap:anywhere]" : "whitespace-pre")
  return (
    <div className="relative min-h-0 flex-1 bg-[var(--rw-deep)]">
      <pre ref={under} aria-hidden className={`${layer} pointer-events-none select-none`}>{colored}</pre>
      <textarea
        value={value} spellCheck={false} wrap={wrap ? "soft" : "off"} data-raw
        onChange={(event) => onChange(event.target.value)}
        onScroll={(event) => {
          if (!under.current) return
          under.current.scrollTop = event.currentTarget.scrollTop
          under.current.scrollLeft = event.currentTarget.scrollLeft
        }}
        className={`${layer} resize-none border-0 bg-transparent text-transparent caret-[var(--foreground)] outline-none`}
      />
    </div>
  )
}
