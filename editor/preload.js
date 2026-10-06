// The page's API to the main process (main.js), exposed as window.workshop.
// Each call returns a promise that rejects with the main process's error
// message; `config` (the section list and Make targets) is available
// synchronously, since blocks.js reads it while loading.
"use strict";

const { contextBridge, ipcRenderer } = require("electron");

const PREFIX = "--resume-workshop-config=";
const config = JSON.parse(process.argv.find((arg) => arg.startsWith(PREFIX)).slice(PREFIX.length));

async function invoke(channel, ...args) {
  const result = await ipcRenderer.invoke(channel, ...args);
  if (result && result.error !== undefined) throw new Error(result.error);
  return result;
}

contextBridge.exposeInMainWorld("workshop", {
  config,
  files: () => invoke("files"),
  save: (name, content) => invoke("save", name, content),
  make: (target) => invoke("make", target),
  pdf: () => invoke("pdf"),
  openPdf: () => invoke("open-pdf"),
});
