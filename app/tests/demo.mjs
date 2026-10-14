// Records docs/screenshots/demo.gif, the animated tour of the editor at the
// top of the main README, in a headless browser, on a copy of this
// checkout's resume in a temporary folder. It drives the editor through its
// main features (typing with the live preview, bold, testing a link, the ATS
// check, the section cards, the color themes, and a build), taking a picture
// of the window at each step, with a caption under it. Run with
// `npm run demo` after `npm run build`; it needs what the smoke test does
// (tests/smoke.mjs), and ffmpeg to put the pictures together. The link test
// asks the resume's own portfolio site for a page; offline, that step just
// shows the buttons.
import { execFileSync, spawn } from "node:child_process"
import { cpSync, existsSync, mkdirSync, mkdtempSync, rmSync, statSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer-core"

const app = join(dirname(fileURLToPath(import.meta.url)), "..")
const root = join(app, "..")
const output = join(root, "docs", "screenshots", "demo.gif")
const chrome = [process.env.CHROME, "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].find((path) => path && existsSync(path))
if (!chrome) throw new Error("No Chrome or Chromium found; set $CHROME.")
const scratch = mkdtempSync(join(tmpdir(), "resume-workshop-demo-"))
const folder = join(scratch, "resume")
const pictures = join(scratch, "pictures")
const environment = { ...process.env, XDG_CONFIG_HOME: join(scratch, "config"), RESUME_WORKSHOP_ROOT: folder, PYTHONDONTWRITEBYTECODE: "1" }
const port = 3900 + Math.floor(Math.random() * 90)
const size = { width: 1500, height: 1000 } // the window
const SCALE = 0.64 // the GIF is the window at this size, to keep the file small
const CAPTION_HEIGHT = 46
const JOB = `Senior Machine Learning Engineer

Build and deploy machine learning models for predictive maintenance and anomaly detection on IoT telemetry.
- Python, PyTorch and SQL; AWS (SageMaker) and Snowflake
- MLOps: CI/CD, model governance and drift detection
- Kubernetes and Terraform are a plus
`

let server, browser
try {
  execFileSync("python3", ["-c", "import sys; sys.path.insert(0, sys.argv[1]); import project; project.create(sys.argv[2])", join(app, "backend"), folder], { env: environment })
  cpSync(join(root, "input"), join(folder, "input"), { recursive: true })
  cpSync(join(root, "etc", "dictionary.txt"), join(folder, "etc", "dictionary.txt"))
  cpSync(join(root, "output", "resume.pdf"), join(folder, "output", "resume.pdf"))
  mkdirSync(pictures)
  server = spawn("python3", [join(app, "backend", "devserver.py"), String(port)], { env: environment, stdio: ["ignore", "pipe", "inherit"] })
  await new Promise((resolve) => server.stdout.once("data", resolve))
  browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", `--window-size=${size.width},${size.height}`] })
  const page = await browser.newPage()
  await page.setViewport(size)
  await page.goto(`http://127.0.0.1:${port}/`)
  await page.waitForSelector("canvas", { timeout: 120000 })

  const frames = [] // each picture's caption, and how long it shows, in ms
  const pause = (ms = 400) => new Promise((resolve) => setTimeout(resolve, ms))
  const picture = (index) => `${String(index).padStart(3, "0")}.png`
  /** Takes a picture of the window, to show for `ms` with `caption` under it. */
  const frame = async (caption, ms) => {
    await page.screenshot({ path: join(pictures, `window-${picture(frames.length)}`) })
    frames.push([caption, ms])
  }
  const button = (text) => page.evaluate((label) => [...document.querySelectorAll("button")].find((entry) => entry.textContent === label).click(), text)
  const press = async (key, ...held) => {
    for (const modifier of held) await page.keyboard.down(modifier)
    await page.keyboard.press(key)
    for (const modifier of held.reverse()) await page.keyboard.up(modifier)
  }
  /** Scrolls the block editor so that the card titled `title` is at its top. */
  const scrollTo = (title) => page.evaluate((text) => {
    const heading = [...document.querySelectorAll("section header div, section > div.font-semibold")].find((entry) => entry.textContent.trim().startsWith(text))
    heading.closest("section").scrollIntoView({ block: "start" })
  }, title)
  const menu = async (name) => {
    await page.evaluate((label) => [...document.querySelectorAll("nav button")].find((entry) => entry.textContent === label).click(), name)
    await page.waitForSelector('[role="menu"]')
  }
  const choose = async (label) => (await page.waitForFunction((text) => [...document.querySelectorAll('[role="menuitem"], [role="menuitemradio"]')].find((entry) => entry.textContent.startsWith(text)), {}, label)).click()
  /** Scrolls the field whose text starts with `text` into view, and selects `words` in it (or puts the cursor at its end). */
  const field = async (text, words = "") => {
    const found = await page.evaluateHandle((start) => [...document.querySelectorAll("[data-field]")].find((entry) => entry.value.startsWith(start)), text)
    await found.evaluate((entry, selected) => {
      entry.scrollIntoView({ block: "center" })
      entry.focus()
      const at = selected ? entry.value.indexOf(selected) : entry.value.length
      entry.setSelectionRange(at, at + selected.length)
    }, words)
    await pause()
    return found
  }
  /** Waits for the live preview to show what is in the editor. */
  const previewed = async () => {
    await pause(300)
    await page.waitForFunction(() => document.querySelector("[data-preview-note]")?.textContent === "Preview includes unsaved changes.", { timeout: 120000 })
    await pause(1200) // for the PDF's pages to be drawn
  }

  await frame("Resume Workshop: edit a JSON Resume in cards, with the PDF beside it", 2800)

  // Typing, with the live preview following.
  let caption = "Live preview: the PDF rebuilds as you type"
  await field("Senior Data Scientist")
  await frame(caption, 1200)
  for (const letter of " · AI") {
    await page.keyboard.sendCharacter(letter)
    await pause(60)
    await frame(caption, 170)
  }
  await previewed()
  await frame(caption, 2600)

  // Bold, in the summary, whose text the preview marks.
  caption = "Bold the words that matter: select them and press B"
  await field("Built the labor time model", "16% to 95%")
  await page.waitForSelector("[data-highlight]", { timeout: 20000 })
  await pause(600)
  await frame(caption, 1800)
  await (await page.evaluateHandle(() => [...document.querySelectorAll("[data-toolbar] button")].find((entry) => entry.textContent === "B"))).click()
  await previewed()
  await frame(caption, 2600)

  // Links.
  caption = "Test and open the resume's links from the editor"
  const portfolio = await field("https://portfolio")
  await frame(caption, 1500)
  const test = await portfolio.evaluateHandle((entry) => [...entry.closest("div.flex").querySelectorAll("button")].find((found) => found.textContent === "Test"))
  await test.click()
  await page.waitForFunction((entry) => entry.textContent.length > 1 && entry.textContent !== "Test", { timeout: 20000 }, test).catch(() => undefined)
  await pause(200)
  await frame(caption, 2600)

  // The ATS check.
  const ats = await page.$('header button[title^="ATS check"]')
  await ats.click()
  await page.waitForFunction(() => /\d+ fine, \d+ to note, \d+ to fix\./.test(document.querySelector("aside")?.textContent ?? ""), { timeout: 20000 })
  await frame("ATS check: how an applicant tracking system is likely to read the resume", 3000)
  await page.focus("aside textarea")
  await page.keyboard.sendCharacter(JOB)
  await page.waitForFunction(() => document.querySelector("aside").textContent.includes("main terms"), { timeout: 20000 })
  await pause()
  await frame("Paste a job description to see which of its terms the resume has", 3200)
  await ats.click()
  await pause()

  // The section cards.
  await button("Collapse all")
  await scrollTo("Sections")
  await pause()
  await frame("Drag sections to reorder them; each has its own card, heading, and page break", 3000)

  // The color themes.
  for (const theme of ["Nord", "Gruvbox Dark", "Solarized Dark", "Solarized Light", "Light", "Dracula"]) {
    await menu("View")
    await choose("Color Theme")
    await choose(theme)
    await press("Escape")
    await press("Escape")
    await pause(300)
    await page.evaluate(() => document.activeElement.blur()) // the menu's button, which gets the focus back as the menu closes
    await pause(300)
    await frame(`Six color themes: ${theme}`, 1100)
  }

  // A build.
  await button("Expand all")
  await scrollTo("Header")
  await button("Save & build")
  await page.waitForFunction(() => /^(Built|The build failed)/.test(document.querySelector("[data-status]").textContent), { timeout: 180000 })
  await pause(1500)
  if ((await page.$eval("[data-status]", (element) => element.textContent)).startsWith("Built")) {
    await frame("Build: the PDF, a plain-text resume, and a Reactive Resume export", 3200)
  }

  // Each picture, made smaller, over its caption. (Afterwards, as a second page would take the window's place on show.)
  const shown = { width: Math.round(size.width * SCALE), height: Math.round(size.height * SCALE) }
  await page.setViewport({ width: shown.width, height: shown.height + CAPTION_HEIGHT })
  for (const [index, [caption]] of frames.entries()) {
    await page.goto(`file://${join(pictures, `window-${picture(index)}`)}`)
    await page.evaluate((text, { width, height }, captionHeight) => {
      document.body.style.cssText = "margin:0;display:block;background:#191a21;color:#f8f8f2;font:bold 19px sans-serif;overflow:hidden"
      document.querySelector("img").style.cssText = `display:block;width:${width}px;height:${height}px`
      const under = document.body.appendChild(document.createElement("div"))
      under.style.cssText = `width:${width}px;line-height:${captionHeight}px;text-align:center`
      under.textContent = text
    }, caption, shown, CAPTION_HEIGHT)
    await page.screenshot({ path: join(pictures, picture(index)) })
  }

  // A GIF's pictures share 256 colors here, which keeps the file small; that is enough for the themes' accents.
  // (The last picture is listed twice, as the list's last entry has no length of its own.)
  const listed = frames.map(([, ms], index) => `file '${picture(index)}'\nduration ${ms / 1000}\n`).join("")
  writeFileSync(join(pictures, "list.txt"), `${listed}file '${picture(frames.length - 1)}'\n`)
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-i", join(pictures, "list.txt"), "-fps_mode", "vfr",
    "-filter_complex", "split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=none", "-loop", "0", output])
  console.log(`Recorded demo.gif: ${frames.length} pictures, ${Math.round(frames.reduce((sum, [, ms]) => sum + ms, 0) / 1000)} s, ${(statSync(output).size / 1e6).toFixed(1)} MB.`)
} finally {
  await browser?.close()
  server?.kill()
  rmSync(scratch, { recursive: true, force: true })
}
