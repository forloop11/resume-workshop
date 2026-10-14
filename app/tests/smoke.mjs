// Drives the editor's window in a headless browser, against the real
// backend (backend/devserver.py) and a new resume folder in a temporary
// directory: opens it, edits a field, waits for the live preview, saves,
// and builds. Run with `npm run smoke` after `npm run build`; it needs
// Python with jsonschema, a TeX engine, and Chrome or Chromium
// ($CHROME, or the usual places).
import { execFileSync, spawn } from "node:child_process"
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer-core"

const app = join(dirname(fileURLToPath(import.meta.url)), "..")
const chrome = [process.env.CHROME, "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].find((path) => path && existsSync(path))
if (!chrome) throw new Error("No Chrome or Chromium found; set $CHROME.")
const scratch = mkdtempSync(join(tmpdir(), "resume-workshop-smoke-"))
const folder = join(scratch, "resume")
const environment = { ...process.env, XDG_CONFIG_HOME: join(scratch, "config"), RESUME_WORKSHOP_ROOT: folder, PYTHONDONTWRITEBYTECODE: "1" }
const port = 3200 + Math.floor(Math.random() * 500)
const shots = process.env.SHOTS // a folder to leave screenshots in

let server, browser
function check(condition, what) {
  if (!condition) throw new Error(`Failed: ${what}`)
  console.log(`ok  ${what}`)
}

try {
  execFileSync("python3", ["-c", "import sys; sys.path.insert(0, sys.argv[1]); import project; project.create(sys.argv[2])", join(app, "backend"), folder], { env: environment })
  server = spawn("python3", [join(app, "backend", "devserver.py"), String(port)], { env: environment, stdio: ["ignore", "pipe", "inherit"] })
  await new Promise((resolve) => server.stdout.once("data", resolve))

  browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--window-size=1500,1000"] })
  const page = await browser.newPage()
  await page.setViewport({ width: 1500, height: 1000 })
  const errors = []
  page.on("pageerror", (error) => errors.push(String(error)))
  page.on("console", (entry) => entry.type() === "error" && errors.push(entry.text()))
  await page.goto(`http://127.0.0.1:${port}/`)
  const status = () => page.$eval("[data-status]", (element) => element.textContent)
  const shot = async (name) => shots && (await page.screenshot({ path: join(shots, `${name}.png`) }))

  await page.waitForSelector("[data-field]")
  check((await page.title()).includes("resume"), "the window opens the resume folder")
  const name = await page.$("[data-field]")
  check((await name.evaluate((field) => field.value)) === "Your Name", "the Header card shows the resume's name")

  await page.waitForSelector("canvas", { timeout: 120000 })
  check(true, "the live preview shows the PDF")
  await shot("opened")

  await name.focus()
  await name.evaluate((field) => field.select())
  await name.type("Ada Example")
  await page.waitForFunction(() => [...document.querySelectorAll("button")].some((button) => button.textContent === "Resume (blocks) •"))
  check(true, "an edit marks the tab as unsaved")
  await page.waitForSelector("[data-preview-note]", { timeout: 120000 })
  check((await page.$eval("[data-preview-note]", (note) => note.textContent)) === "Preview includes unsaved changes.", "the live preview follows the edit")
  // (Not the name itself, which the PDF prints in capitals.)
  await page.evaluate(() => [...document.querySelectorAll("textarea[data-field]")].find((field) => field.value.startsWith("Two or three sentences")).focus())
  await page.waitForSelector("[data-highlight]", { timeout: 10000 })
  check(true, "the preview highlights the field being edited")
  await new Promise((resolve) => setTimeout(resolve, 1500))
  await shot("edited")

  await page.keyboard.down("Control")
  await page.keyboard.press("s")
  await page.keyboard.up("Control")
  await page.waitForFunction(() => document.querySelector("[data-status]").textContent.startsWith("Saved"))
  const onDisk = JSON.parse(readFileSync(join(folder, "input", "resume.json"), "utf8")).basics.name
  check(onDisk === "Ada Example", `Ctrl+S saves input/resume.json (${await status()}; the name on disk is ${onDisk})`)

  // A required field left empty isn't saved.
  await name.focus()
  await name.evaluate((field) => field.select())
  await page.keyboard.press("Backspace")
  await page.keyboard.down("Control")
  await page.keyboard.press("s")
  await page.keyboard.up("Control")
  await page.waitForFunction(() => document.querySelector("[data-status]").textContent.startsWith("Not saved"))
  check((await status()).includes("name is required"), "a save with a required field empty is turned down")
  check((await name.evaluate((field) => field.getAttribute("aria-invalid"))) === "true", "...and the field is highlighted")
  await name.type("Ada Example")

  // Add a highlight, then take it back with Undo.
  const count = () => page.$$eval("[data-field]", (fields) => fields.length)
  const before = await count()
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "+ Add highlight").click())
  check((await count()) === before + 1, "+ Add highlight adds a field")
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "Undo").click())
  await page.waitForFunction((fields) => document.querySelectorAll("[data-field]").length === fields, {}, before)
  check(true, "Undo takes it back")

  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "Save & build").click())
  await page.waitForFunction(() => /^(Built|The build failed)/.test(document.querySelector("[data-status]").textContent), { timeout: 180000 })
  check((await status()).startsWith("Built the resume"), `Save & build builds the resume (${await status()})`)
  for (const built of ["resume.pdf", "resume.txt", "rxresume.json", "resume-workshop.json"]) check(existsSync(join(folder, "output", built)), `output/${built} is written`)
  check(readFileSync(join(folder, "output", "resume.txt"), "utf8").includes("ADA EXAMPLE"), "the text resume has the edit")

  // The raw tab shows the same document.
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "resume.json").click())
  const raw = await page.waitForSelector("textarea.font-mono")
  check((await raw.evaluate((area) => area.value)).includes('"name": "Ada Example"'), "the resume.json tab shows the blocks' edits")
  check((await page.$$eval("pre span", (keys) => keys.map((key) => key.textContent))).includes('"basics"'), "...with its keys colored")
  await shot("raw")

  // The ATS check.
  await page.keyboard.down("Control")
  await page.keyboard.down("Shift")
  await page.keyboard.press("A")
  await page.keyboard.up("Shift")
  await page.keyboard.up("Control")
  await page.waitForFunction(() => /\d+ fine, \d+ to note, \d+ to fix\./.test(document.body.textContent), { timeout: 20000 })
  check(true, "Ctrl+Shift+A opens the ATS check, with its findings")
  await shot("ats")

  // Find and Replace, in the raw tab and then the blocks.
  const press = async (key, ...held) => {
    for (const modifier of held) await page.keyboard.down(modifier)
    await page.keyboard.press(key)
    for (const modifier of held.reverse()) await page.keyboard.up(modifier)
  }
  const place = () => page.$eval("[data-find-place]", (element) => element.textContent)
  await press("f", "Control")
  await page.waitForSelector("[data-find-bar] input")
  await page.keyboard.type("example")
  await page.waitForFunction(() => /^1 of \d+$/.test(document.querySelector("[data-find-place]").textContent))
  const inRaw = Number((await place()).split(" of ")[1])
  check(inRaw >= 3, `Ctrl+F finds matches in resume.json (${await place()})`)
  await press("F3")
  check((await place()) === `2 of ${inRaw}`, "F3 goes to the next match")
  await press("Escape")
  check((await page.evaluate(() => document.activeElement.value.slice(document.activeElement.selectionStart, document.activeElement.selectionEnd).toLowerCase())) === "example",
    "Esc leaves the match selected in the text")

  await press("1", "Control")
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "Collapse all").click())
  await press("h", "Control")
  await page.waitForSelector("[data-find-bar] input")
  await page.keyboard.type("Institution")
  await page.waitForFunction(() => document.querySelector("[data-find-place]").textContent === "1 of 1")
  check(await page.$eval("[data-find-current]", (field) => field.offsetParent !== null), "a match in a collapsed card opens the card")
  await page.type('[data-find-bar] input[placeholder="Replace with"]', "Example University")
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "Replace all").click())
  await page.waitForFunction(() => document.querySelector("[data-status]").textContent === "Replaced 1 match.")
  check(await page.evaluate(() => [...document.querySelectorAll("[data-field]")].some((field) => field.value === "Example University")), "Replace all types the replacement into the field")
  await press("Escape")

  // Spelling: a misspelled word is underlined, its correction a click away; a word of the resume's own can be added to the folder's list.
  await page.evaluate(() => [...document.querySelectorAll("button")].find((button) => button.textContent === "Expand all").click())
  const position = await page.evaluateHandle(() => [...document.querySelectorAll("textarea[data-field]")].find((field) => field.value === "Position"))
  await position.evaluate((field) => {
    field.scrollIntoView()
    field.focus()
    field.select()
  })
  await page.keyboard.type("Sentense writer at Acmecorp")
  await page.waitForFunction(() => document.querySelectorAll('.grow-mirror mark[data-kind="spelling"]').length === 2, { timeout: 30000 })
  check(true, "misspelled words are underlined")
  await page.evaluate(() => [...document.querySelectorAll("[data-spelling] button")].find((button) => button.textContent === "Sentence").click())
  check((await position.evaluate((field) => field.value)) === "Sentence writer at Acmecorp", "...and a correction is a click away")
  await page.evaluate(() => [...document.querySelectorAll("[data-spelling] button")].find((button) => button.textContent === "Add to dictionary").click())
  await page.waitForFunction(() => document.querySelectorAll('.grow-mirror mark[data-kind="spelling"]').length === 0)
  await page.waitForFunction(() => document.querySelector("[data-status]").textContent.startsWith("Added"))
  check(readFileSync(join(folder, "etc", "dictionary.txt"), "utf8") === "Acmecorp\n", "Add to dictionary adds the word to the folder's etc/dictionary.txt")

  // Grammar, where the checker (an optional extra, which needs Java) is there to run.
  const summary = await page.evaluateHandle(() => [...document.querySelectorAll("textarea[data-field]")].find((field) => field.value.startsWith("Two or three sentences")))
  await summary.evaluate((field) => {
    field.scrollIntoView()
    field.focus()
    field.select()
  })
  await page.keyboard.type("She go to the office every day.")
  // Asked of the backend itself: the window says so only once, as it opens.
  const off = await page.evaluate(() => fetch("/rpc", { method: "POST", body: JSON.stringify({ id: 0, method: "grammar", params: { texts: ["She go."] } }) })
    .then((response) => response.json()).then((answer) => answer.result.off))
  if (off) {
    console.log(`--  grammar isn't checked here (${off})`)
  } else {
    await page.waitForSelector('.grow-mirror mark[data-kind="grammar"]', { timeout: 120000 })
    check((await page.$eval('.grow-mirror mark[data-kind="grammar"]', (mark) => mark.textContent)) === "go", "a grammar problem is underlined")
    await page.waitForSelector("[data-grammar] button")
    await page.evaluate(() => [...document.querySelectorAll("[data-grammar] button")].find((button) => button.textContent === "goes").click())
    check((await summary.evaluate((field) => field.value)) === "She goes to the office every day.", "...and its fix is a click away")
  }

  // The preview's highlight covers the whole field: past bold words (their own run of text in the PDF), an
  // apostrophe (printed curly), and a bold mark left half typed.
  for (const [typed, pieces] of [["It's a **bold** claim about Ada's work, and it holds up.", 3], ["A **half typed mark, and the rest of the sentence.", 1]]) {
    await summary.evaluate((field) => {
      field.focus()
      field.select()
    })
    await page.keyboard.type(typed)
    await page.waitForFunction(() => document.querySelector("[data-preview-note]")?.textContent === "Preview includes unsaved changes.", { timeout: 120000 })
    const covered = () => page.evaluate((text) => {
      // The marks' widths, against that of the line they are on: all of it, if the whole sentence is covered.
      const marks = [...document.querySelectorAll("[data-highlight]")]
      return { marks: marks.length, width: marks.reduce((sum, mark) => sum + mark.getBoundingClientRect().width, 0), text }
    }, typed)
    await page.waitForFunction((count) => document.querySelectorAll("[data-highlight]").length >= count, { timeout: 20000 }, pieces)
    check((await covered()).marks >= pieces, `the highlight covers all of “${typed}” (${(await covered()).marks} pieces)`)
  }
  await shot("highlight")

  // Print PDF lays the built PDF's pages out for the system's print dialog.
  await page.evaluate(() => (window.print = () => (window.printed = document.querySelectorAll("#print-pages img").length)))
  await press("p", "Control")
  await page.waitForFunction(() => window.printed !== undefined, { timeout: 60000 })
  check((await page.evaluate(() => window.printed)) === 1, "Ctrl+P sends the PDF's page to the print dialog")

  // Help > Third-Party Licenses.
  await page.evaluate(() => [...document.querySelectorAll("nav button")].find((button) => button.textContent === "Help").click())
  const item = await page.waitForFunction(() => [...document.querySelectorAll('[role="menuitem"]')].find((entry) => entry.textContent === "Third-Party Licenses"))
  await item.click()
  await page.waitForSelector("[data-licenses]")
  check((await page.$eval("[data-licenses]", (text) => text.textContent)).includes("pdfjs-dist"), "Third-Party Licenses lists what the window includes")

  check(errors.length === 0, `no errors in the page${errors.length ? `: ${errors.join(" | ")}` : ""}`)
  console.log("All passed.")
} finally {
  await browser?.close()
  server?.kill()
  rmSync(scratch, { recursive: true, force: true })
}
