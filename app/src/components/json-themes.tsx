// Theme > JSON Resume Themes: the resume as a web page, in one of the JSON
// Resume themes from npm (lib/json-themes.ts). The page shown is of the
// resume as it is in the window, saved or not; it can be exported as an
// HTML file, or opened in the web browser, which prints it or saves it as
// a PDF.
import * as React from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { openPath, pickSave, rpc } from "@/lib/bridge"
import { contained, JSON_THEMES, renderJsonTheme } from "@/lib/json-themes"
import { cn } from "@/lib/utils"

const REMEMBERED = "json-resume-theme"
const message = (error: unknown) => String((error as Error)?.message ?? error)

export function JsonThemes({ resume, root, home, report, onClose }: {
  resume: string
  root: string
  home: string
  report(text: string, kind?: string): void
  onClose(): void
}) {
  const [theme, setTheme] = React.useState(() => {
    const remembered = window.localStorage.getItem(REMEMBERED)
    return JSON_THEMES.some((known) => known.id === remembered) ? remembered! : JSON_THEMES[0].id
  })
  const [page, setPage] = React.useState<{ theme: string; html: string } | null>(null)
  const [failure, setFailure] = React.useState("")
  const chosen = JSON_THEMES.find((known) => known.id === theme)!

  React.useEffect(() => {
    let current = true
    window.localStorage.setItem(REMEMBERED, theme)
    renderJsonTheme(theme, resume)
      .then((html) => current && (setPage({ theme, html }), setFailure("")))
      .catch((error) => current && (setPage(null), setFailure(`The ${chosen.name} theme could not show this resume: ${message(error)}`)))
    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, resume])

  /** Writes the page to a file of the user's choosing, or to output/resume.html to open in the web browser. */
  async function write(open: boolean) {
    if (!page) return
    try {
      let target: string | null = null
      if (!open) {
        const name = (await rpc<string>("export_name", { root, kind: "html" }))
        target = await pickSave(`Export the ${chosen.name} page`, name, [{ name: "HTML", extensions: ["html"] }], home)
        if (!target) return
      }
      const written = await rpc<{ path: string }>("write_html", { root, html: page.html, target })
      if (!open) return report(`Exported the resume in the ${chosen.name} theme to ${written.path}.`, "ok")
      const opened = await openPath(written.path).catch(() => false)
      report(opened ? `Opened ${written.path} in the web browser, which can print it or save it as a PDF.` : `The page is at ${written.path}.`, opened ? "ok" : "")
    } catch (error) {
      report(message(error), "error")
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="flex h-[88vh] flex-col sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>JSON Resume Themes</DialogTitle>
          <DialogDescription>
            The resume as a web page, in a theme made for JSON Resume. A theme lays out the standard fields in its own order; the PDF and its Resume Theme aren't changed.
          </DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 gap-3">
          <div className="flex w-56 shrink-0 flex-col gap-1 overflow-y-auto" role="radiogroup" aria-label="Theme">
            {JSON_THEMES.map((known) => (
              <button
                key={known.id} type="button" role="radio" aria-checked={known.id === theme} data-json-theme={known.id} onClick={() => setTheme(known.id)}
                className={cn("rounded-md border px-2.5 py-1.5 text-left", known.id === theme ? "border-primary bg-accent" : "border-transparent hover:bg-accent")}
              >
                <div className="font-medium">{known.name}</div>
                <div className="text-xs text-muted-foreground">{known.about}</div>
              </button>
            ))}
          </div>
          {failure ? <div className="flex-1 text-destructive" data-json-theme-failure>{failure}</div> : (
            // sandbox: nothing in a theme's page runs here.
            <iframe title={`The resume in the ${chosen.name} theme`} sandbox="" srcDoc={page ? contained(page.html) : ""} data-json-theme-page={page?.theme ?? ""} className="min-w-0 flex-1 rounded-md border border-border bg-white" />
          )}
        </div>
        <div className="flex items-center justify-end gap-2">
          <span className="flex-1 text-xs text-muted-foreground">Shown without web fonts or pictures from the network, which some themes use in the exported page.</span>
          <Button variant="outline" disabled={!page} onClick={() => void write(true)}>Open in Browser</Button>
          <Button disabled={!page} onClick={() => void write(false)}>Export HTML…</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
