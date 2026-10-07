// Desktop editor for the input files and Makefile targets (`make editor`).
//
// The main process does what a local web server would: it reads and writes
// the files in input/, runs the Makefile targets, points the page at the
// generated PDF, and saves copies of the Reactive Resume export. The page (index.html, with the drag-and-drop block editor in
// blocks.js) reaches these through the API in preload.js. Section names and
// the JSON Resume schema check come from scripts/editor_backend.py, so the
// editor and the generators share one copy of each.
"use strict";

const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const ROOT = path.resolve(__dirname, "..");
const INPUT_DIR = path.join(ROOT, "input");
const PDF = path.join(ROOT, "output", "resume.pdf");
const RXRESUME = path.join(ROOT, "output", "rxresume.json");
const BACKEND = path.join(ROOT, "scripts", "editor_backend.py");
const EDITABLE_FILES = ["format.tex", "geometry.yaml", "section_order.yaml", "resume.json"];
const MAKE_TARGETS = ["build", "user"];

// Runs a command to completion and resolves with its exit code and output.
// Rejects only if the command can't be started (e.g. it isn't installed).
function run(command, args, { cwd = ROOT, input } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd });
    let stdout = "", stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", (error) => reject(new Error(`Could not run ${command}: ${error.message}`)));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
    child.stdin.end(input);
  });
}

// Runs editor_backend.py and parses its JSON output; a failure (such as
// jsonschema not being installed) throws with the script's message.
async function backend(command, input) {
  const { code, stdout, stderr } = await run("python3", [BACKEND, command], { cwd: path.dirname(BACKEND), input });
  if (code) throw new Error(stderr.trim() || `editor_backend.py ${command} failed`);
  return JSON.parse(stdout);
}

async function pdfUrl() {
  try {
    await fs.access(PDF);
  } catch {
    return null;
  }
  // The timestamp makes the viewer reload the file after each build.
  return `${pathToFileURL(PDF).href}?ts=${Date.now()}`;
}

async function saveFile(name, content) {
  if (!EDITABLE_FILES.includes(name) || typeof content !== "string") throw new Error("Invalid input file");
  if (name === "resume.json") {
    // resume.json is a JSON Resume document; refuse to save one that
    // doesn't match the schema (etc/resume-schema.json).
    const errors = await backend("check", content);
    if (errors.length) throw new Error("resume.json does not match the JSON Resume schema: " + errors.join("; "));
  }
  await fs.writeFile(path.join(INPUT_DIR, name), content, "utf8");
  return { message: `Saved input/${name}.` };
}

async function make(target) {
  if (!MAKE_TARGETS.includes(target)) throw new Error("Invalid Make target");
  const { code, stdout, stderr } = await run("make", [target]);
  const output = stdout + stderr;
  if (code) throw new Error(output || `make ${target} failed`);
  return { output: output || `make ${target} completed.`, pdf: await pdfUrl() };
}

// Regenerates output/rxresume.json from the saved input files and asks
// where to save a copy.
async function downloadRxresume() {
  const { code, stdout, stderr } = await run("make", ["rxresume"]);
  if (code) throw new Error(stdout + stderr || "make rxresume failed");
  const options = {
    title: "Save Reactive Resume export",
    defaultPath: path.join(app.getPath("downloads"), "rxresume.json"),
    filters: [{ name: "JSON", extensions: ["json"] }],
  };
  const win = BrowserWindow.getFocusedWindow();
  const { canceled, filePath } = await (win ? dialog.showSaveDialog(win, options) : dialog.showSaveDialog(options));
  if (canceled || !filePath) return { canceled: true, message: "Download canceled." };
  await fs.copyFile(RXRESUME, filePath);
  return { message: `Saved the Reactive Resume export to ${filePath}.` };
}

// Each handler resolves with its result, or with { error } so the page gets
// the plain message instead of Electron's "Error invoking remote method" one.
function handle(channel, fn) {
  ipcMain.handle(channel, async (_event, ...args) => {
    try {
      return await fn(...args);
    } catch (error) {
      return { error: error.message };
    }
  });
}

handle("files", async () => {
  const files = {};
  for (const name of EDITABLE_FILES) files[name] = await fs.readFile(path.join(INPUT_DIR, name), "utf8");
  return { files };
});
handle("save", saveFile);
handle("make", make);
handle("pdf", async () => ({ url: await pdfUrl() }));
handle("download-rxresume", downloadRxresume);
handle("open-pdf", async () => {
  if (!(await pdfUrl())) throw new Error("Build the resume before viewing the PDF.");
  const error = await shell.openPath(PDF);
  if (error) throw new Error(error);
  return {};
});

function createWindow(config) {
  const win = new BrowserWindow({
    width: 1500,
    height: 1000,
    backgroundColor: "#191a21",
    title: "Resume Workshop",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      // The page reads this synchronously at startup (see preload.js).
      additionalArguments: [`--resume-workshop-config=${JSON.stringify(config)}`],
    },
  });

  // The page cancels unloading (closing or reloading the window) while
  // there are unsaved changes; ask whether to discard them.
  win.webContents.on("will-prevent-unload", (event) => {
    const choice = dialog.showMessageBoxSync(win, {
      type: "question",
      buttons: ["Discard changes", "Keep editing"],
      defaultId: 1,
      cancelId: 1,
      message: "Discard unsaved changes?",
      detail: "Some edits haven't been saved to input/.",
    });
    if (choice === 0) event.preventDefault();
  });

  // Keep the window on the editor page; send any web links to the browser.
  win.webContents.on("will-navigate", (event) => event.preventDefault());
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });

  win.loadFile(path.join(__dirname, "index.html"));
}

app.whenReady().then(async () => {
  let sections;
  try {
    sections = await backend("sections");
  } catch (error) {
    dialog.showErrorBox("Resume Workshop", `The editor needs python3 (3.13 or newer) to start.\n\n${error.message}`);
    app.quit();
    return;
  }
  createWindow({ sections, targets: MAKE_TARGETS });
});

app.on("window-all-closed", () => app.quit());
