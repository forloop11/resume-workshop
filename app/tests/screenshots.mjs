// Retakes the editor's screenshots in the main README (docs/screenshots/),
// in a headless browser, on a copy of this checkout's resume in a temporary
// folder. Run with `npm run screenshots` after `npm run build`; it needs
// what the smoke test does (tests/smoke.mjs).
import { execFileSync, spawn } from "node:child_process"
import { cpSync, existsSync, mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import puppeteer from "puppeteer-core"

const app = join(dirname(fileURLToPath(import.meta.url)), "..")
const root = join(app, "..")
const shots = join(root, "docs", "screenshots")
const chrome = [process.env.CHROME, "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"].find((path) => path && existsSync(path))
if (!chrome) throw new Error("No Chrome or Chromium found; set $CHROME.")
const scratch = mkdtempSync(join(tmpdir(), "resume-workshop-screenshots-"))
const folder = join(scratch, "resume")
const environment = { ...process.env, XDG_CONFIG_HOME: join(scratch, "config"), RESUME_WORKSHOP_ROOT: folder, PYTHONDONTWRITEBYTECODE: "1" }
const port = 3700 + Math.floor(Math.random() * 200)
const size = { width: 1500, height: 1000 }

let server, browser
try {
  execFileSync("python3", ["-c", "import sys; sys.path.insert(0, sys.argv[1]); import project; project.create(sys.argv[2])", join(app, "backend"), folder], { env: environment })
  cpSync(join(root, "input"), join(folder, "input"), { recursive: true })
  cpSync(join(root, "output", "resume.pdf"), join(folder, "output", "resume.pdf"))
  server = spawn("python3", [join(app, "backend", "devserver.py"), String(port)], { env: environment, stdio: ["ignore", "pipe", "inherit"] })
  await new Promise((resolve) => server.stdout.once("data", resolve))
  browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", `--window-size=${size.width},${size.height}`] })
  const page = await browser.newPage()
  await page.setViewport(size)
  await page.goto(`http://127.0.0.1:${port}/`)
  await page.waitForSelector("canvas", { timeout: 120000 })

  const pause = (ms = 400) => new Promise((resolve) => setTimeout(resolve, ms))
  const shot = async (name) => {
    await pause()
    await page.screenshot({ path: join(shots, `${name}.png`) })
    console.log(`${name}.png`)
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

  // The window, with the summary's text highlighted in the preview.
  await page.evaluate(() => document.querySelector("textarea[data-field]").focus())
  await page.waitForSelector("[data-highlight]", { timeout: 20000 })
  await shot("editor-window")
  await shot("editor-blocks")

  // The section cards, with Education open.
  await button("Collapse all")
  await page.evaluate(() => [...document.querySelectorAll("section header")].find((header) => header.textContent.startsWith("Education")).click())
  await scrollTo("Professional Summary")
  await shot("editor-blocks-sections")

  // Experience, with the first employer open.
  await page.evaluate(() => [...document.querySelectorAll("section header")].find((header) => header.textContent.startsWith("Professional Experience")).click())
  await page.evaluate(() => document.querySelector("section section header").click())
  await scrollTo("Professional Experience")
  await shot("editor-blocks-experience")

  // The Find bar, with a match selected.
  await press("f", "Control")
  await page.waitForSelector("[data-find-bar] input")
  await page.keyboard.type("model")
  await page.waitForFunction(() => /^1 of \d+$/.test(document.querySelector("[data-find-place]").textContent))
  await press("F3")
  await shot("editor-find")
  await press("Escape")

  // Page Setup.
  await press("P", "Control", "Shift")
  await page.waitForSelector('[role="dialog"]')
  await shot("editor-page-setup")
  await button("Cancel")

  // The raw resume.json tab.
  await press("2", "Control")
  await shot("editor-resume-json")
  await press("1", "Control")
  await button("Expand all")
  await scrollTo("Header")

  // The File menu.
  await menu("File")
  await shot("editor-file-menu")
  await press("Escape")

  // Each color theme, side by side.
  const themes = []
  for (const theme of ["Dracula", "Nord", "Gruvbox Dark", "Solarized Dark", "Solarized Light", "Light"]) {
    await menu("Theme")
    await choose("Color Theme")
    await choose(theme)
    await press("Escape")
    await press("Escape")
    await pause()
    themes.push([theme, await page.screenshot({ encoding: "base64" })])
  }
  const sheet = await browser.newPage()
  await sheet.setViewport({ width: 1500, height: 720 })
  await sheet.setContent(`<body style="margin:0;background:#222;display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:6px;font:14px sans-serif;color:#eee">${themes.map(([name, image]) =>
    `<figure style="margin:0"><img src="data:image/png;base64,${image}" style="width:100%;display:block"><figcaption style="text-align:center;padding:3px">${name}</figcaption></figure>`).join("")}</body>`)
  await sheet.screenshot({ path: join(shots, "editor-themes.png"), fullPage: true })
  console.log("editor-themes.png")
} finally {
  await browser?.close()
  server?.kill()
  rmSync(scratch, { recursive: true, force: true })
}
