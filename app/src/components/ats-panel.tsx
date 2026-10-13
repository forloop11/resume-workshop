// The ATS check: how an applicant tracking system is likely to read the
// resume (scripts/check_ats.py, through the backend), kept up to date a
// moment after the resume's text stops changing; and which of a job
// description's terms the resume has.
import * as React from "react"

import { rpc } from "@/lib/bridge"

const MARKS: Record<string, [string, string]> = { ok: ["✓", "var(--rw-ok)"], note: ["•", "var(--rw-warning)"], warn: ["✗", "var(--destructive)"] }
const DELAY = 600 // ms after the last change

type Result = { findings: { level: string; text: string }[]; match: { found: string[]; missing: string[] } | null }

export function AtsPanel({ resume, order }: { resume: string; order: string }) {
  const [job, setJob] = React.useState("")
  const [result, setResult] = React.useState<Result | null>(null)

  React.useEffect(() => {
    let current = true
    const timer = window.setTimeout(() => {
      rpc<Result>("ats", { resume, order, job }).then((found) => current && setResult(found)).catch(() => undefined)
    }, DELAY)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [resume, order, job])

  const count = (level: string) => result?.findings.filter((finding) => finding.level === level).length ?? 0
  return (
    <aside className="flex w-80 shrink-0 flex-col gap-2 rounded-xl border border-border bg-card p-3 text-sm">
      <div className="font-semibold">ATS check</div>
      <div className="min-h-24 flex-[3] overflow-y-auto rounded-lg bg-[var(--rw-deep)] p-2 select-text">
        {result ? (<>
          <div className="mb-1.5 font-semibold">{count("ok")} fine, {count("note")} to note, {count("warn")} to fix.</div>
          {result.findings.map((finding, index) => (
            <div key={index} className="mb-1 flex gap-2">
              <span style={{ color: MARKS[finding.level]?.[1] }}>{MARKS[finding.level]?.[0]}</span>
              <span>{finding.text}</span>
            </div>
          ))}
        </>) : "Checking…"}
      </div>
      <textarea
        value={job} onChange={(event) => setJob(event.target.value)} placeholder="Paste a job description here to see which of its terms the resume has."
        className="min-h-20 flex-[2] resize-none rounded-lg border border-input bg-[var(--rw-deep)] p-2 outline-none focus-visible:border-ring"
      />
      <div className="min-h-16 flex-[2] overflow-y-auto rounded-lg bg-[var(--rw-deep)] p-2 select-text">
        {result?.match ? (<>
          <div className="font-semibold">The resume has {result.match.found.length} of the job's {result.match.found.length + result.match.missing.length} main terms.</div>
          <div className="mt-1"><span style={{ color: "var(--destructive)" }}>Missing: </span>{result.match.missing.join(", ") || "none"}</div>
          <div className="mt-1"><span style={{ color: "var(--rw-ok)" }}>Found: </span>{result.match.found.join(", ") || "none"}</div>
        </>) : <span className="text-muted-foreground">The job description's terms appear here.</span>}
      </div>
    </aside>
  )
}
