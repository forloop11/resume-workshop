// Drives the real app -- the Tauri window, its web view, and the backend it
// starts -- through WebDriver, where the smoke test (smoke.mjs) drives the
// window alone in Chrome: opens a new resume folder, edits a field, waits
// for the live preview, saves with the keyboard, and closes the window.
// Run with `npm run window` after `npm run tauri build -- --no-bundle`. It
// needs tauri-driver (`cargo install tauri-driver --locked`) and the
// system's WebKitWebDriver, and shows the window while it runs.
import { execFileSync, spawn } from "node:child_process"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { homedir, tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const app = join(dirname(fileURLToPath(import.meta.url)), "..")
const program = join(app, "src-tauri", "target", "release", "resume-workshop")
const driver = [process.env.TAURI_DRIVER, join(homedir(), ".cargo", "bin", "tauri-driver")].find((path) => path && existsSync(path))
if (!existsSync(program)) throw new Error("Build the app first: npm run tauri build -- --no-bundle")
if (!driver) throw new Error("No tauri-driver found: cargo install tauri-driver --locked")
const scratch = mkdtempSync(join(tmpdir(), "resume-workshop-window-"))
const folder = join(scratch, "resume")
const environment = { ...process.env, XDG_CONFIG_HOME: join(scratch, "config"), RESUME_WORKSHOP_ROOT: folder, PYTHONDONTWRITEBYTECODE: "1" }
const port = 4444
const KEYS = { control: "", null: "" }

function check(condition, what) {
  if (!condition) throw new Error(`Failed: ${what}`)
  console.log(`ok  ${what}`)
}

/** One WebDriver command. */
async function command(method, path, body) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined })
  const answer = await response.json()
  if (answer.value?.error) throw new Error(`${path}: ${answer.value.message}`)
  return answer.value
}

let server, session
try {
  execFileSync("python3", ["-c", "import sys; sys.path.insert(0, sys.argv[1]); import project; project.create(sys.argv[2])", join(app, "backend"), folder], { env: environment })
  server = spawn(driver, ["--port", String(port)], { env: environment, stdio: "ignore" })
  await new Promise((resolve) => setTimeout(resolve, 1500))
  session = (await command("POST", "/session", { capabilities: { alwaysMatch: { "tauri:options": { application: program }, browserName: "wry" } } })).sessionId
  const at = `/session/${session}`
  const script = (code, ...args) => command("POST", `${at}/execute/sync`, { script: code, args })
  const until = async (code, what, seconds = 120) => {
    for (const end = Date.now() + seconds * 1000; Date.now() < end; await new Promise((resolve) => setTimeout(resolve, 250))) {
      if (await script(`return Boolean(${code})`)) return check(true, what)
    }
    check(false, `${what} (the status line: ${await script(`return document.querySelector("[data-status]")?.textContent`)}; the first field: ${await script(`return document.querySelector("[data-field]")?.value`)})`)
  }

  await until(`document.querySelector("[data-field]")`, "the app opens the resume folder, through its backend")
  check((await script(`return document.querySelector("[data-field]").value`)) === "Your Name", "the Header card shows the resume's name")
  await until(`document.querySelector("canvas")`, "the live preview draws the PDF in the web view")

  const name = (await command("POST", `${at}/element`, { using: "css selector", value: "[data-field]" }))["element-6066-11e4-a52e-4f735466cecf"]
  await script(`document.querySelector("[data-field]").focus(); document.querySelector("[data-field]").select()`)
  await command("POST", `${at}/element/${name}/value`, { text: "Ada Example" }) // over what is there
  await until(`[...document.querySelectorAll("button")].some((button) => button.textContent === "Resume (blocks) •")`, "typing in a field marks the tab as unsaved")
  await until(`document.querySelector("[data-preview-note]")`, "the live preview follows the edit")
  await until(`document.querySelectorAll(".grow-mirror").length > 5`, "the fields have their spelling layer")

  await command("POST", `${at}/element/${name}/value`, { text: `${KEYS.control}s${KEYS.null}` })
  await until(`document.querySelector("[data-status]").textContent.startsWith("Saved")`, "Ctrl+S saves", 20)
  const saved = JSON.parse(readFileSync(join(folder, "input", "resume.json"), "utf8")).basics.name
  check(saved === "Ada Example", `...to input/resume.json (the name there is ${saved})`)

  await script(`[...document.querySelectorAll("button")].find((button) => button.textContent === "Save & build").click()`)
  await until(`/^(Built|The build failed)/.test(document.querySelector("[data-status]").textContent)`, "Save & build finishes", 180)
  check((await script(`return document.querySelector("[data-status]").textContent`)).startsWith("Built the resume"), "...and builds the resume")
  check(existsSync(join(folder, "output", "resume.pdf")), "output/resume.pdf is written")

  await script(`[...document.querySelectorAll("nav button")].find((button) => button.textContent === "File").click()`)
  await until(`[...document.querySelectorAll('[role="menuitem"]')].some((item) => item.textContent.startsWith("Quit"))`, "the File menu opens, with Quit", 10)
  console.log("All passed.")
} finally {
  if (session) await command("DELETE", `/session/${session}`).catch(() => undefined)
  server?.kill()
  rmSync(scratch, { recursive: true, force: true })
}
