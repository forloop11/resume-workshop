// The editor's window: tabs that edit a resume folder's input files -- the
// block editor (components/blocks.tsx) and the raw resume.json -- beside a
// live preview of the PDF, under a menu bar with every command. What the
// commands do happens in the backend (backend/server.py, through
// lib/bridge.ts).
import * as React from "react"
import { Menu } from "lucide-react"

import { AtsPanel } from "@/components/ats-panel"
import { Blocks, type BlocksHandle } from "@/components/blocks"
import { FindBar, type FindHandle } from "@/components/find-bar"
import { PageSetup } from "@/components/page-setup"
import { RawEditor } from "@/components/raw-editor"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuRadioGroup, DropdownMenuRadioItem,
  DropdownMenuSeparator, DropdownMenuShortcut, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { confirm, isTauri, openPath, openUrl, pickFile, pickFolder, pickSave, rpc, type Filter } from "@/lib/bridge"
import { parseGeometry, type Section } from "@/lib/model"
import { applyTheme, type Theme } from "@/lib/themes"
import { cn } from "@/lib/utils"

// The PDF preview, with PDF.js, is loaded apart from the rest of the window, which shows first.
const PdfView = React.lazy(() => import("@/components/pdf-view").then((module) => ({ default: module.PdfView })))
// The JSON Resume themes, and what they are built on, are loaded when their dialog is first opened.
const JsonThemes = React.lazy(() => import("@/components/json-themes").then((module) => ({ default: module.JsonThemes })))
const SLOW = 6000 // ms after which a build says why it may be taking a while

const RESUME = "resume.json"
const ORDER = "section_order.yaml"
const GEOMETRY = "geometry.yaml"
const RELEASES = "https://github.com/forloop11/resume-workshop/releases"
const PREVIEW_DELAY = 900 // ms after the last change
// The commands that don't need a resume folder to be open.
const ALWAYS = new Set(["New Resume…", "Open Resume Folder…", "Quit"])
const UNSAVED = "Some edits haven't been saved to input/. Discard them?"

type Layout = { id: string; name: string; about: string }
type Boot = {
  version: string | null; channel: string; store: boolean; themes: Record<string, Theme>; theme: string; layouts: Layout[]; sections: Section[]
  folder: string | null; reason: string; recent: { folder: string; short: string }[]; home: string
  launcher: { available: boolean; installed: boolean }
}
type Files = Record<string, string>
type Folder = { root: string; short: string }
type Opened = Folder & { files: Files; notice: { text: string; kind: string }; pdf: string | null; words: string[]; layout: string | null }
type Command = { label: string; keys?: string; run: () => void; disabled?: boolean; checked?: boolean }
/** A submenu to choose one of several from. */
type Choice = { label: string; value: string; options: { value: string; label: string; title?: string }[]; choose: (value: string) => void; always?: boolean }

const message = (error: unknown) => String((error as Error)?.message ?? error)

/** "Ctrl+Shift+A" as the keyboard event that means it. */
function pressed(event: KeyboardEvent, keys: string) {
  const parts = keys.toLowerCase().split("+")
  const key = parts[parts.length - 1]
  return (event.ctrlKey || event.metaKey) === parts.includes("ctrl") && event.shiftKey === parts.includes("shift") && event.altKey === parts.includes("alt")
    && (event.key.toLowerCase() === key || event.code.toLowerCase() === `key${key}` || event.code.toLowerCase() === `digit${key}`)
}

export function App() {
  const [boot, setBoot] = React.useState<Boot | null>(null)
  const [fault, setFault] = React.useState("")
  const [folder, setFolder] = React.useState<Folder | null>(null)
  const [files, setFiles] = React.useState<Files>({})
  const [saved, setSaved] = React.useState<Files>({})
  const [status, setStatus] = React.useState({ text: "", kind: "" })
  const [tab, setTab] = React.useState<"blocks" | "raw">("blocks")
  const [pdf, setPdf] = React.useState<string | null>(null)
  const [shown, setShown] = React.useState<string | null>(null) // the text the preview shows, once known
  const [failed, setFailed] = React.useState<{ key: string; reason: string } | null>(null) // ...and the text that last failed to build
  const [output, setOutput] = React.useState("")
  const [outputOpen, setOutputOpen] = React.useState(false)
  const [building, setBuilding] = React.useState(false)
  const [atsOpen, setAtsOpen] = React.useState(false)
  const [live, setLive] = React.useState(true)
  const [wrap, setWrap] = React.useState(true)
  const [theme, setTheme] = React.useState("")
  const [layout, setLayout] = React.useState<string | null>(null) // the resume theme input/format.tex is, if it is one of them
  const [geometryDraft, setGeometryDraft] = React.useState<string | null>(null) // geometry.yaml as Page Setup is editing it
  const [pageSetup, setPageSetup] = React.useState(false)
  const [about, setAbout] = React.useState(false)
  const [jsonThemes, setJsonThemes] = React.useState(false)
  const [focusText, setFocusText] = React.useState("")
  const [words, setWords] = React.useState<string[]>([]) // the folder's own spelling list
  const [sideWidth, setSideWidth] = React.useState(470)
  const [finding, setFinding] = React.useState<"" | "find" | "replace">("")
  const [newer, setNewer] = React.useState<any>(null) // the release Check for Updates found
  const [licenses, setLicenses] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState("") // what is being installed, if anything
  const [activity, setActivity] = React.useState("") // what is going on in the background, for a line beside the title
  const [updated, setUpdated] = React.useState(false) // an update has been installed, and the editor can restart into it
  const blocks = React.useRef<BlocksHandle>(null)
  const finder = React.useRef<FindHandle>(null)
  const panel = React.useRef<HTMLDivElement>(null)
  const previews = React.useRef(0)

  const report = React.useCallback((text: string, kind = "") => setStatus({ text, kind }), [])
  const dirty = (name: string) => files[name] !== saved[name]
  const anyDirty = dirty(RESUME) || dirty(ORDER)
  const key = (content: Files, geometry = content[GEOMETRY]) => [content[RESUME], content[ORDER], geometry].join("\u0000")
  const current = key(files, geometryDraft ?? files[GEOMETRY])

  // --- folders -----------------------------------------------------------------------

  function show(opened: Opened) {
    setFolder({ root: opened.root, short: opened.short })
    setFiles(opened.files)
    setSaved(opened.files)
    setPdf(opened.pdf)
    setWords(opened.words)
    setLayout(opened.layout)
    setShown(null)
    setFailed(null)
    setOutput("")
    setGeometryDraft(null)
    report(opened.notice.text, opened.notice.kind)
    document.title = `Resume Workshop — ${opened.short}`
    return opened
  }

  React.useEffect(() => {
    rpc<Boot>("startup")
      .then(async (started) => {
        setBoot(started)
        setTheme(started.theme)
        applyTheme(started.themes[started.theme])
        if (started.folder) show(await rpc<Opened>("open", { folder: started.folder }))
      })
      .catch((error) => setFault(message(error)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Switches to the resume in `path`, asking about unsaved changes first. */
  async function openFolder(path: string | null, create = false) {
    if (!path) return
    if (building) return report("Wait for the build to finish before opening another resume.")
    if (folder && anyDirty && !(await confirm(UNSAVED, "Discard changes"))) return
    try {
      const opened = show(await rpc<Opened>(create ? "create" : "open", { folder: path }))
      if (!opened.notice.text) report(`Opened ${opened.short}.`, "ok")
      setBoot((before) => before && { ...before, recent: [] })
      rpc("recent").then((recent) => setBoot((before) => before && { ...before, recent }))
    } catch (error) {
      report(message(error), "error")
    }
  }

  const newResume = async () => openFolder(await pickFolder("New Resume: choose a new or empty folder", boot?.home ?? ""), true)
  const openResume = async () => openFolder(await pickFolder("Open Resume Folder", boot?.home ?? ""))

  async function reload() {
    if (!folder) return
    if (anyDirty && !(await confirm("Discard unsaved changes and reload all files from disk?", "Reload"))) return
    try {
      const read = await rpc<Files>("read", { root: folder.root })
      setFiles(read)
      setSaved(read)
    } catch (error) {
      report(message(error), "error")
    }
  }

  // --- saving ------------------------------------------------------------------------

  /** Writes the files that changed; false if it couldn't. */
  async function write(names: string[], said?: string) {
    if (!folder) return false
    try {
      await rpc("save", { root: folder.root, files: Object.fromEntries(names.map((name) => [name, files[name]])) })
    } catch (error) {
      report(message(error), "error")
      return false
    }
    setSaved((before) => ({ ...before, ...Object.fromEntries(names.map((name) => [name, files[name]])) }))
    report(said ?? `Saved ${names.map((name) => `input/${name}`).join(" and ")}.`, "ok")
    return true
  }

  /** Saves the tab that is showing; false if it couldn't. */
  async function saveCurrent() {
    if (tab === "raw") {
      try {
        JSON.parse(files[RESUME])
      } catch (error) {
        report(`Cannot save ${RESUME}: invalid JSON — ${message(error)}`, "error")
        return false
      }
      return write([RESUME], `Saved input/${RESUME}.`)
    }
    try {
      const problems = (await blocks.current?.validate()) ?? []
      if (problems.length) {
        report(`Not saved — ${problems.length} problem${problems.length === 1 ? "" : "s"}: ${problems.join(" ")}`, "error")
        return false
      }
    } catch (error) {
      report(message(error), "error")
      return false
    }
    const changed = [RESUME, ORDER].filter(dirty)
    if (!changed.length) {
      report("No changes to save.")
      return true
    }
    const duplicates = blocks.current?.duplicates() ?? 0
    const warning = duplicates ? ` Core Competencies has ${duplicates} duplicate${duplicates === 1 ? "" : "s"}.` : ""
    return write(changed, `Saved ${changed.map((name) => `input/${name}`).join(" and ")}.${warning}`)
  }

  // --- building and the PDF ----------------------------------------------------------

  function buildFailed(text: string) {
    setOutput(text)
    setOutputOpen(true)
    report('The build failed — see "Last build output".', "error")
  }

  /** Builds everything in output/ from the saved input files, as `make build` does. */
  async function runBuild(named = false) {
    if (!folder) return
    if (building) return report("A build is already running.")
    setBuilding(true)
    report("Building the resume...")
    const slow = window.setTimeout(() => setActivity("Still building. The first build can take a while: Tectonic may be downloading the TeX packages the layout loads."), SLOW)
    try {
      const built = await rpc("build", { root: folder.root, named })
      if (!built.ok) return buildFailed(built.output)
      setOutput(built.output)
      setPdf(built.pdf)
      setShown(key({ ...saved, [GEOMETRY]: files[GEOMETRY] }))
      report(built.message, "ok")
    } catch (error) {
      report(message(error), "error")
    } finally {
      window.clearTimeout(slow)
      setActivity("")
      setBuilding(false)
    }
  }

  const saveAndBuild = async () => (await saveCurrent()) && runBuild()

  // The live preview: a moment after the resume's text stops changing, it is built into a PDF, saved or not.
  React.useEffect(() => {
    if (!folder || !live || current === shown || current === failed?.key) return
    const timer = window.setTimeout(async () => {
      const run = ++previews.current
      const built = await rpc("preview", { root: folder.root, resume: files[RESUME], order: files[ORDER], geometry: geometryDraft ?? files[GEOMETRY] })
        .catch((error) => ({ ok: false, reason: message(error) }))
      if (run !== previews.current) return // the text has changed since
      if (built.ok) {
        setPdf(built.pdf)
        setShown(current)
        setFailed(null)
      } else {
        setFailed({ key: current, reason: built.reason })
      }
    }, PREVIEW_DELAY)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folder?.root, live, current, shown, failed?.key])

  async function setLivePreview(on: boolean) {
    setLive(on)
    if (!on && folder) {
      // Back to output/resume.pdf.
      setPdf((await rpc("pdf", { root: folder.root })).pdf)
      setShown(null)
      setFailed(null)
    }
  }

  const note = !live ? "" : current === failed?.key ? `Preview not updated: ${failed.reason}`
    : current === shown && (anyDirty || geometryDraft !== null) ? "Preview includes unsaved changes." : ""

  async function openPdf() {
    if (!folder) return
    const built = await rpc("pdf", { root: folder.root })
    if (!built.pdf) return report("Build the resume before viewing the PDF.", "error")
    if (!(await openPath(built.path).catch(() => false))) report(`The PDF is at ${built.path}.`)
  }

  /** Prints output/resume.pdf, after the system's dialog asks which printer and pages. */
  async function print() {
    if (!folder) return
    const built = await rpc("pdf", { root: folder.root })
    if (!built.pdf) return report("Build the resume before printing the PDF.", "error")
    try {
      await (await import("@/components/pdf-view")).printPdf(built.pdf)
    } catch (error) {
      report(`Could not print resume.pdf: ${message(error)}`, "error")
    }
  }

  // --- the editor itself -------------------------------------------------------------

  async function checkForUpdates() {
    report("Checking for updates…")
    try {
      const checked = await rpc("check_update")
      if (checked.state === "newer") {
        report("")
        setNewer(checked)
      } else {
        report(checked.message, checked.state === "latest" ? "ok" : "")
      }
    } catch (error) {
      report(message(error), "error")
    }
  }

  async function installUpdate() {
    setBusy("Downloading the update…")
    try {
      report((await rpc("install_update")).message, "ok")
      setUpdated(true)
    } catch (error) {
      report(message(error), "error")
    } finally {
      setBusy("")
    }
  }

  /** Starts the editor again, as after an update: the new version, on the same resume folder. */
  async function restart() {
    if (anyDirty && !(await confirm(UNSAVED, "Discard changes"))) return
    unsaved.current = false
    const { invoke } = await import("@tauri-apps/api/core")
    await invoke("restart")
  }

  /** Downloads the optional grammar checker for this user, after asking, and starts it. */
  async function installGrammar() {
    const grammar = await rpc("grammar_status")
    const verb = grammar.installed ? "Update" : "Install"
    const question = `${verb} the grammar checker?\n\nThis downloads language-tool-python and what it needs, a few megabytes, from the Python Package Index into `
      + `${grammar.packages}. It is separate from Resume Workshop, and under a license of its own (the GPL, version 3).\n\n`
      + "Grammar checking also needs Java, and downloads LanguageTool itself, about 260 MB, the first time it runs. "
      + "The resume's text is checked on this machine, and isn't sent anywhere."
    if (!(await confirm(question, verb))) return
    setBusy("Installing the grammar checker…")
    report("Installing the grammar checker…")
    try {
      const installed = await rpc("install_grammar")
      if (!installed.ok) {
        setOutput(installed.output)
        setOutputOpen(true)
        report('The grammar checker could not be installed — see "Last build output".', "error")
      } else if (installed.updated) {
        report("Updated the grammar checker; the new version starts the next time the editor does.", "ok")
      } else {
        blocks.current?.retryGrammar()
        report("Installed the grammar checker. It starts now, and marks grammar in a moment.", "ok")
      }
    } catch (error) {
      report(message(error), "error")
    } finally {
      setBusy("")
    }
  }

  /** The licenses of the window's own libraries (written as it is built), and of what a packaged editor carries. */
  async function showLicenses() {
    const bundled = await fetch("THIRD-PARTY-LICENSES.txt").then((response) => (response.ok ? response.text() : "")).catch(() => "")
    const carried = await rpc<string>("licenses").catch(() => "")
    setLicenses([bundled, carried].filter(Boolean).join("\n\n") || "No licenses were found.")
  }

  /** The text boxes Find looks through: the showing tab's, in order. */
  const findTargets = () => [...(panel.current?.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>(tab === "blocks" ? "[data-field]" : "[data-raw]") ?? [])]
  const find = (backward = false) => (finding ? finder.current?.find(backward) : setFinding("find"))

  async function exportAs(kind: string, what: string, filter: Filter) {
    if (!folder) return
    const name = await rpc<string>("export_name", { root: folder.root, kind })
    const target = await pickSave(`Export ${what}`, name, [filter], boot?.home ?? "")
    if (!target) return report("Export canceled.")
    report(`Exporting ${what}...`)
    try {
      const exported = await rpc("export", { root: folder.root, kind, target })
      if (!exported.ok) return buildFailed(exported.output)
      report(`Exported ${what} to ${target}.${anyDirty ? " It has the saved files only; save and export again to include your unsaved changes." : ""}`, "ok")
    } catch (error) {
      report(message(error), "error")
    }
  }

  async function importJson() {
    const path = await pickFile("Import JSON Resume", boot?.home ?? "", [{ name: "JSON", extensions: ["json"] }])
    if (!path) return
    try {
      const imported = await rpc("import_json", { path })
      if (!(await confirm(`Replace the resume in the editor with ${imported.name}?\n\ninput/${RESUME} itself isn't changed until you save.`, "Replace"))) return
      setFiles((before) => ({ ...before, [RESUME]: imported.text }))
      const problems: string[] = imported.problems
      if (problems.length) {
        const shownProblems = problems.slice(0, 3).join("; ") + (problems.length > 3 ? `; and ${problems.length - 3} more` : "")
        report(`Imported ${path}, which doesn't match the JSON Resume schema: ${shownProblems}. Fix that before saving.`, "error")
      } else {
        report(`Imported ${path}. Save to keep it.`, "ok")
      }
    } catch (error) {
      report(message(error), "error")
    }
  }

  async function updateBuildFiles() {
    if (!folder) return
    const notice = await rpc("notice", { root: folder.root })
    const stale: string[] = notice.stale ?? []
    if (!stale.length) return report("This folder's build files already match the editor's.", "ok")
    const question = `Update this folder's build files?\n\nThis replaces ${stale.join(", ")} in ${folder.short} with the editor's copies. Changes you made to them there are lost; the resume and its layout in input/ aren't touched.`
    if (!(await confirm(question, "Update"))) return
    try {
      await rpc("update_build_files", { root: folder.root })
      report(`Updated ${stale.join(", ")} in ${folder.short}.`, "ok")
    } catch (error) {
      report(message(error), "error")
    }
  }

  function openPageSetup() {
    try {
      parseGeometry(files[GEOMETRY])
      setPageSetup(true)
    } catch (error) {
      report(`Page Setup can't edit input/${GEOMETRY} (${message(error)}); edit the file in a text editor.`, "error")
    }
  }

  async function closePageSetup(text: string | null) {
    setPageSetup(false)
    setGeometryDraft(null)
    if (text === null || text === files[GEOMETRY] || !folder) return
    try {
      await rpc("save", { root: folder.root, files: { [GEOMETRY]: text } })
      setFiles((before) => ({ ...before, [GEOMETRY]: text }))
      setSaved((before) => ({ ...before, [GEOMETRY]: text }))
      report(`Saved input/${GEOMETRY}. Build the resume to update output/resume.pdf.`, "ok")
    } catch (error) {
      report(message(error), "error")
    }
  }

  /** Makes one of the resume themes the folder's layout (input/format.tex), asking before a layout that isn't one of them is replaced. */
  async function chooseLayout(id: string) {
    const chosen = boot?.layouts.find((option) => option.id === id)
    if (!folder || !chosen || id === layout) return
    if (building) return report("Wait for the build to finish before changing the resume's theme.")
    const question = `Replace this resume's layout with the ${chosen.name} theme?\n\ninput/format.tex in ${folder.short} isn't one of the editor's themes as they are now, `
      + "so it may have changes of your own, which would be lost."
    if (layout === null && !(await confirm(question, "Replace"))) return
    try {
      const changed = await rpc("set_layout", { root: folder.root, name: id })
      setLayout(changed.layout)
      // The preview is of the layout before.
      setShown(null)
      setFailed(null)
      report(changed.notice.text || `The resume's theme is now ${chosen.name}. Build the resume to update output/resume.pdf.`, changed.notice.text ? changed.notice.kind : "ok")
    } catch (error) {
      report(message(error), "error")
    }
  }

  function chooseTheme(name: string) {
    if (!boot) return
    setTheme(name)
    applyTheme(boot.themes[name])
    void rpc("set_theme", { name })
  }

  function formatJson() {
    try {
      setFiles((before) => ({ ...before, [RESUME]: JSON.stringify(JSON.parse(before[RESUME]), null, 2) }))
      report(`Formatted ${RESUME}. Click "Save file" to persist.`)
    } catch (error) {
      report(`Cannot format ${RESUME}: ${message(error)}`, "error")
    }
  }

  /** Adds the AppImage to the applications menu, or takes it out. */
  async function toggleLauncher() {
    try {
      const changed = await rpc("toggle_launcher")
      setBoot((before) => before && { ...before, launcher: { available: changed.available, installed: changed.installed } })
      report(changed.message, "ok")
    } catch (error) {
      report(message(error), "error")
    }
  }

  async function toggleFullScreen() {
    if (isTauri()) {
      const { getCurrentWindow } = await import("@tauri-apps/api/window")
      const window = getCurrentWindow()
      await window.setFullscreen(!(await window.isFullscreen()))
    } else if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else {
      await document.documentElement.requestFullscreen()
    }
  }

  /** Closes the window, which asks about unsaved changes first (see onCloseRequested below). */
  async function quit() {
    if (isTauri()) {
      const { getCurrentWindow } = await import("@tauri-apps/api/window")
      await getCurrentWindow().close()
    } else {
      window.close()
    }
  }

  // --- menus -------------------------------------------------------------------------

  const onBlocks = tab === "blocks"
  const edit = (command: string) => () => document.execCommand(command)
  const menus: [string, (Command | null | Choice | { label: string; items: Command[] })[]][] = [
    ["File", [
      { label: "New Resume…", keys: "Ctrl+N", run: newResume },
      { label: "Open Resume Folder…", keys: "Ctrl+O", run: openResume },
      {
        label: "Open Recent",
        items: (boot?.recent ?? []).filter((recent) => recent.folder !== folder?.root).map((recent) => ({ label: recent.short, run: () => void openFolder(recent.folder) })),
      },
      null,
      { label: "Save", keys: "Ctrl+S", run: saveCurrent },
      { label: "Save & Build", keys: "Ctrl+B", run: saveAndBuild },
      { label: "Reload from Disk", keys: "Ctrl+R", run: reload },
      null,
      { label: "Build Resume", run: () => void runBuild() },
      { label: "Build and Name PDF", run: () => void runBuild(true) },
      { label: "Update Folder's Build Files…", run: updateBuildFiles },
      { label: "ATS Check", keys: "Ctrl+Shift+A", run: () => setAtsOpen(!atsOpen), checked: atsOpen },
      null,
      { label: "Page Setup…", keys: "Ctrl+Shift+P", run: openPageSetup },
      { label: "Print PDF…", keys: "Ctrl+P", run: print },
      { label: "Open PDF", keys: "Ctrl+Shift+O", run: openPdf },
      null,
      { label: "Import JSON Resume…", keys: "Ctrl+I", run: importJson },
      { label: "Export PDF…", keys: "Ctrl+E", run: () => void exportAs("pdf", "the PDF", { name: "PDF", extensions: ["pdf"] }) },
      { label: "Export TXT…", run: () => void exportAs("txt", "the text resume", { name: "Text", extensions: ["txt"] }) },
      { label: "Export JSON…", run: () => void exportAs("json", "the JSON Resume", { name: "JSON", extensions: ["json"] }) },
      { label: "Download rxresume.json…", run: () => void exportAs("rxresume", "the Reactive Resume file", { name: "JSON", extensions: ["json"] }) },
      null,
      { label: "Quit", keys: "Ctrl+Q", run: quit },
    ]],
    ["Edit", [
      { label: "Undo", keys: "Ctrl+Z", run: edit("undo") },
      { label: "Redo", keys: "Ctrl+Shift+Z", run: edit("redo") },
      { label: "Undo Block Change", keys: "Ctrl+Alt+Z", run: () => blocks.current?.undo(), disabled: !onBlocks || !blocks.current?.canUndo() },
      null,
      { label: "Select All", keys: "Ctrl+A", run: edit("selectAll") },
      null,
      { label: "Find…", keys: "Ctrl+F", run: () => setFinding("find") },
      { label: "Find Next", keys: "F3", run: () => find() },
      { label: "Find Previous", keys: "Shift+F3", run: () => find(true) },
      { label: "Replace…", keys: "Ctrl+H", run: () => setFinding("replace") },
      null,
      { label: "Bold", keys: "Ctrl+Shift+B", run: () => blocks.current?.toggleBold(), disabled: !onBlocks },
      { label: "Insert Middle Dot (·)", keys: "Ctrl+.", run: () => blocks.current?.insertChar("·"), disabled: !onBlocks },
      { label: "Insert En Dash (–)", keys: "Ctrl+-", run: () => blocks.current?.insertChar("–"), disabled: !onBlocks },
      { label: "Pretty-print JSON", run: formatJson, disabled: onBlocks },
      // An app store's build may not fetch code.
      ...(boot?.store ? [] : [null, { label: "Install or Update Grammar Checker…", run: installGrammar, disabled: !!busy }]),
    ]],
    ["View", [
      { label: "Resume (blocks)", keys: "Ctrl+1", run: () => setTab("blocks") },
      { label: RESUME, keys: "Ctrl+2", run: () => setTab("raw") },
      null,
      { label: "Expand All", keys: "Ctrl+Shift+E", run: () => blocks.current?.setAllOpen(true), disabled: !onBlocks },
      { label: "Collapse All", keys: "Ctrl+Shift+C", run: () => blocks.current?.setAllOpen(false), disabled: !onBlocks },
      { label: "Wrap Lines", run: () => setWrap(!wrap), checked: wrap, disabled: onBlocks },
      null,
      { label: "Live Preview", run: () => void setLivePreview(!live), checked: live },
      { label: "Full Screen", keys: "F11", run: toggleFullScreen },
    ]],
    ["Theme", [
      {
        label: "Resume Theme", value: layout ?? "", choose: (id: string) => void chooseLayout(id),
        options: (boot?.layouts ?? []).map((option) => ({ value: option.id, label: option.name, title: option.about })),
      },
      { label: "JSON Resume Themes…", run: () => setJsonThemes(true) },
      null,
      // The editor's own colors, whatever resume is open.
      { label: "Color Theme", value: theme, choose: chooseTheme, options: Object.keys(boot?.themes ?? {}).map((option) => ({ value: option, label: option })), always: true },
    ]],
    ["Help", [
      // The store updates its own.
      ...(boot?.store ? [] : [{ label: "Check for Updates…", run: checkForUpdates }]),
      // In the AppImage, which is a file wherever it was downloaded to.
      ...(boot?.launcher.available ? [{ label: boot.launcher.installed ? "Remove from Applications Menu" : "Add to Applications Menu", run: toggleLauncher }] : []),
      { label: "Third-Party Licenses", run: showLicenses },
      { label: "About Resume Workshop", run: () => setAbout(true) },
    ]],
  ]

  // The native shortcuts (undo, select all) are the fields' own; the rest are the menus'.
  const shortcuts = menus.flatMap(([, items]) => items).filter((item): item is Command => !!item && "run" in item && !!item.keys && !["Ctrl+Z", "Ctrl+Shift+Z", "Ctrl+A"].includes(item.keys))
  const latest = React.useRef(shortcuts)
  latest.current = shortcuts
  React.useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const command = latest.current.find((item) => pressed(event, item.keys!))
      if (!command) return
      event.preventDefault()
      if (!command.disabled) command.run()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  // Closing the window with unsaved changes asks first.
  const unsaved = React.useRef(false)
  unsaved.current = anyDirty
  React.useEffect(() => {
    if (!isTauri()) {
      const ask = (event: BeforeUnloadEvent) => unsaved.current && event.preventDefault()
      window.addEventListener("beforeunload", ask)
      return () => window.removeEventListener("beforeunload", ask)
    }
    let stop = () => {}
    import("@tauri-apps/api/window").then(({ getCurrentWindow }) =>
      getCurrentWindow().onCloseRequested(async (event) => {
        if (unsaved.current && !(await confirm(UNSAVED, "Discard changes"))) event.preventDefault()
      }).then((unlisten) => (stop = unlisten)))
    return () => stop()
  }, [])

  // --- the window --------------------------------------------------------------------

  if (fault) return <div className="p-8 text-sm text-destructive">The editor's backend could not be started: {fault}</div>
  if (!boot) return null

  const menuBar = (
    <nav className="flex items-center gap-0.5 border-b border-border bg-[var(--rw-bar)] px-2 py-0.5">
      {menus.map(([name, items]) => (
        <DropdownMenu key={name}>
          <DropdownMenuTrigger render={<Button variant="ghost" size="sm" />}>{name}</DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-64">
            {items.map((item, index) => {
              if (!item) return <DropdownMenuSeparator key={index} />
              if ("options" in item) {
                return (
                  <DropdownMenuSub key={index}>
                    <DropdownMenuSubTrigger disabled={!folder && !item.always}>{item.label}</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuRadioGroup value={item.value} onValueChange={item.choose}>
                        {item.options.map((option) => <DropdownMenuRadioItem key={option.value} value={option.value} title={option.title}>{option.label}</DropdownMenuRadioItem>)}
                      </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                )
              }
              if ("items" in item) {
                return (
                  <DropdownMenuSub key={index}>
                    <DropdownMenuSubTrigger>{item.label}</DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      {item.items.length ? item.items.map((recent) => <DropdownMenuItem key={recent.label} onClick={recent.run}>{recent.label}</DropdownMenuItem>)
                        : <DropdownMenuItem disabled>No other resumes opened yet</DropdownMenuItem>}
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                )
              }
              const keys = item.keys ? <DropdownMenuShortcut>{item.keys}</DropdownMenuShortcut> : null
              return item.checked === undefined
                ? <DropdownMenuItem key={index} disabled={item.disabled || (!folder && !ALWAYS.has(item.label))} onClick={item.run}>{item.label}{keys}</DropdownMenuItem>
                : <DropdownMenuCheckboxItem key={index} checked={item.checked} disabled={item.disabled || !folder} onClick={item.run}>{item.label}{keys}</DropdownMenuCheckboxItem>
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      ))}
    </nav>
  )

  if (!folder) {
    return (
      <div className="flex h-full flex-col">
        {menuBar}
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <h1 className="text-2xl font-bold">Resume Workshop</h1>
          <div className="text-muted-foreground">{boot.reason} Create a new resume, or open the folder of one you have?</div>
          {status.text ? <div className="max-w-xl text-center text-sm whitespace-pre-line text-destructive">{status.text}</div> : null}
          <div className="flex gap-2">
            <Button onClick={newResume}>New Resume…</Button>
            <Button variant="outline" onClick={openResume}>Open Resume…</Button>
          </div>
        </div>
      </div>
    )
  }

  const tabLabel = (name: "blocks" | "raw", text: string, isDirty: boolean) => (
    <button
      type="button" onClick={() => setTab(name)}
      className={cn("border-b-2 px-3 py-1.5 text-sm", tab === name ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}
    >
      {text}{isDirty ? " •" : ""}
    </button>
  )
  const statusColor = { ok: "var(--rw-ok)", error: "var(--destructive)" }[status.kind]

  return (
    <div className="flex h-full flex-col" style={{ background: "linear-gradient(var(--background), var(--rw-window-end))" }}>
      {menuBar}
      <header className="flex items-start gap-4 px-6 pt-4">
        <Button variant={atsOpen ? "default" : "outline"} size="icon" title="ATS check: how an applicant tracking system is likely to read the resume" onClick={() => setAtsOpen(!atsOpen)}>
          <Menu />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-bold">Resume Workshop</h1>
          <div className="text-sm text-muted-foreground">
            Edit source files, run the pipeline, and inspect the generated PDF from one window.
            {activity ? <span className="ml-2 italic" data-activity>{activity}</span> : null}
          </div>
          <div className="ui-selectable min-h-5 text-sm whitespace-pre-line" style={{ color: statusColor }} data-status={status.kind}>{status.text}</div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 gap-3.5 px-6 pt-3 pb-5">
        {atsOpen ? <AtsPanel resume={files[RESUME]} order={files[ORDER]} /> : null}

        <div ref={panel} className="flex min-w-0 flex-1 flex-col rounded-xl border border-border bg-[var(--rw-bar)]">
          <div className="flex border-b border-border px-2">
            {tabLabel("blocks", "Resume (blocks)", anyDirty)}
            {tabLabel("raw", RESUME, dirty(RESUME))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5 border-b border-border p-2" data-toolbar>
            {onBlocks ? (<>
              <Button size="sm" onClick={saveCurrent}>Save</Button>
              <Button variant="outline" size="sm" onClick={saveAndBuild}>Save &amp; build</Button>
              <Button variant="outline" size="sm" disabled={!blocks.current?.canUndo()} onClick={() => blocks.current?.undo()}>Undo</Button>
              <Button variant="outline" size="sm" onClick={() => blocks.current?.setAllOpen(true)}>Expand all</Button>
              <Button variant="outline" size="sm" onClick={() => blocks.current?.setAllOpen(false)}>Collapse all</Button>
              <Button variant="outline" size="sm" onClick={reload}>Reload</Button>
              <div className="flex-1" />
              <span className="text-xs text-muted-foreground" title="Insert at the cursor in the last field you clicked">Insert</span>
              {/* onMouseDown: keep the field's focus and selection */}
              <Button variant="outline" size="sm" className="font-bold" title="Bold the selected words, or the word the cursor is in (Ctrl+Shift+B)" onMouseDown={(event) => event.preventDefault()} onClick={() => blocks.current?.toggleBold()}>B</Button>
              <Button variant="outline" size="sm" title="Middle dot (printed as $\cdot$)" onMouseDown={(event) => event.preventDefault()} onClick={() => blocks.current?.insertChar("·")}>·</Button>
              <Button variant="outline" size="sm" title="En dash (printed as --)" onMouseDown={(event) => event.preventDefault()} onClick={() => blocks.current?.insertChar("–")}>–</Button>
            </>) : (<>
              <Button size="sm" onClick={saveCurrent}>Save file</Button>
              <Button variant="outline" size="sm" onClick={reload}>Reload file</Button>
              <Button variant="outline" size="sm" onClick={formatJson}>Pretty-print JSON</Button>
              <Button variant="outline" size="sm" onClick={() => setWrap(!wrap)}>Wrap: {wrap ? "On" : "Off"}</Button>
            </>)}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto" hidden={!onBlocks}>
            <Blocks
              ref={blocks} resume={files[RESUME]} order={files[ORDER]} sections={boot.sections} report={report} onFocusText={setFocusText}
              words={words} onActivity={setActivity}
              onAddWord={(word) => rpc("add_word", { root: folder.root, word }).then(() => report(`Added “${word}” to etc/dictionary.txt.`, "ok")).catch((error) => report(message(error), "error"))}
              onChange={(resume, order) => setFiles((before) => ({ ...before, [RESUME]: resume, [ORDER]: order }))}
            />
          </div>
          {onBlocks ? null : (
            <RawEditor value={files[RESUME]} wrap={wrap} onChange={(text) => setFiles((before) => ({ ...before, [RESUME]: text }))} />
          )}
          {finding ? (
            <FindBar key={tab} ref={finder} replacing={finding === "replace"} targets={findTargets} report={report} onClose={() => setFinding("")} />
          ) : null}
        </div>

        <div
          className="w-1.5 shrink-0 cursor-col-resize rounded bg-transparent hover:bg-border" title="Drag to resize"
          onPointerDown={(event) => {
            const start = event.clientX
            const width = sideWidth
            const move = (moved: PointerEvent) => setSideWidth(Math.min(Math.max(width + start - moved.clientX, 260), 1200))
            const up = () => {
              window.removeEventListener("pointermove", move)
              window.removeEventListener("pointerup", up)
            }
            window.addEventListener("pointermove", move)
            window.addEventListener("pointerup", up)
          }}
        />

        <div className="flex shrink-0 flex-col gap-3 rounded-xl border border-border bg-[var(--rw-bar)] p-4" style={{ width: sideWidth }}>
          {output ? (
            <div className="rounded-md border border-dashed border-border">
              <button type="button" className="w-full px-2 py-1 text-left text-xs text-muted-foreground" onClick={() => setOutputOpen(!outputOpen)}>
                {outputOpen ? "▾" : "▸"} Last build output
              </button>
              {outputOpen ? <pre className="h-64 overflow-auto bg-[var(--rw-deep)] p-2 text-xs">{output}</pre> : null}
            </div>
          ) : null}
          {note ? <div className="text-sm" data-preview-note>{note}</div> : null}
          <React.Suspense fallback={<div className="min-h-0 flex-1 rounded-lg bg-[var(--rw-deep)]" />}>
            <PdfView data={pdf} phrase={live ? focusText : ""} />
          </React.Suspense>
        </div>
      </div>

      {jsonThemes ? (
        <React.Suspense fallback={null}>
          <JsonThemes resume={files[RESUME]} root={folder.root} home={boot.home} report={report} onClose={() => setJsonThemes(false)} />
        </React.Suspense>
      ) : null}
      {pageSetup ? <PageSetup text={files[GEOMETRY]} onChange={setGeometryDraft} onClose={closePageSetup} /> : null}
      <Dialog open={newer !== null} onOpenChange={(open) => !open && !busy && (setNewer(null), setUpdated(false))}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{updated ? `Resume Workshop ${newer?.version} is installed.` : `Resume Workshop ${newer?.version} is available.`}</DialogTitle>
            <DialogDescription>
              {updated ? "It starts the next time you open the editor, or now if you restart it."
                : newer?.checkout ? "This editor is running from a checkout of the project; update it with git pull."
                : newer?.installable ? `You have ${newer.current}. Updating replaces the AppImage that is running, and then the editor can restart into the new version.`
                : `You have ${newer?.current}. Download the new version from its release page.`}
            </DialogDescription>
          </DialogHeader>
          {newer?.notes ? <pre className="ui-selectable max-h-64 overflow-auto rounded-md bg-[var(--rw-deep)] p-2 text-xs whitespace-pre-wrap">{newer.notes}</pre> : null}
          <div className="flex justify-end gap-2">
            {busy ? <span className="flex-1 self-center text-sm text-muted-foreground">{busy}</span> : null}
            <Button variant="outline" disabled={!!busy} onClick={() => void openUrl(newer.page)}>Release Page</Button>
            {updated ? (isTauri() ? <Button onClick={restart}>Restart Now</Button> : null)
              : newer?.installable ? <Button disabled={!!busy} onClick={installUpdate}>Update</Button> : null}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={licenses !== null} onOpenChange={(open) => !open && setLicenses(null)}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Third-Party Licenses</DialogTitle>
            <DialogDescription>The software Resume Workshop includes, each under its own license.</DialogDescription>
          </DialogHeader>
          <pre className="ui-selectable h-[60vh] overflow-auto rounded-md bg-[var(--rw-deep)] p-3 text-xs whitespace-pre-wrap" data-licenses>{licenses}</pre>
        </DialogContent>
      </Dialog>
      <Dialog open={about} onOpenChange={setAbout}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Resume Workshop</DialogTitle>
            <DialogDescription>{boot.version ? `Version ${boot.version}` : "Running from a checkout"}</DialogDescription>
          </DialogHeader>
          <a className="text-sm text-[var(--rw-link)] underline" href={RELEASES}>{RELEASES}</a>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default App
