// The window's way to everything outside it: the backend (backend/server.py),
// and the system's dialogs. In the Tauri app these go through the shell
// (src-tauri); in a browser, served by backend/devserver.py, the backend is
// reached over HTTP and the dialogs are stood in for by typing a path.
import { invoke, isTauri } from "@tauri-apps/api/core"

let nextId = 1

export async function rpc<T = any>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const request = JSON.stringify({ id: nextId++, method, params })
  const reply = isTauri()
    ? JSON.parse(await invoke<string>("rpc", { request }))
    : await (await fetch("/rpc", { method: "POST", body: request })).json()
  if (reply.error !== undefined) throw new Error(reply.error)
  return reply.result as T
}

export type Filter = { name: string; extensions: string[] }

export async function pickFolder(title: string, start: string): Promise<string | null> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog")
    return (await open({ title, directory: true, defaultPath: start })) as string | null
  }
  return window.prompt(`${title}\n\nThe folder's path:`, start)
}

export async function pickFile(title: string, start: string, filters: Filter[]): Promise<string | null> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog")
    return (await open({ title, defaultPath: start, filters })) as string | null
  }
  return window.prompt(`${title}\n\nThe file's path:`, start)
}

/** Where to save a file, offering `name` in the Downloads folder. */
export async function pickSave(title: string, name: string, filters: Filter[], home: string): Promise<string | null> {
  if (isTauri()) {
    const { save } = await import("@tauri-apps/plugin-dialog")
    const { downloadDir, join } = await import("@tauri-apps/api/path")
    return await save({ title, defaultPath: await join(await downloadDir(), name), filters })
  }
  return window.prompt(`${title}\n\nSave as:`, `${home}/Downloads/${name}`)
}

export async function confirm(question: string, action: string): Promise<boolean> {
  if (isTauri()) {
    const { ask } = await import("@tauri-apps/plugin-dialog")
    return await ask(question, { title: "Resume Workshop", kind: "warning", okLabel: action, cancelLabel: "Keep editing" })
  }
  return window.confirm(question)
}

export async function openUrl(url: string) {
  if (isTauri()) {
    const { openUrl } = await import("@tauri-apps/plugin-opener")
    await openUrl(url)
  } else {
    window.open(url, "_blank", "noopener")
  }
}

/** Opens a file in the system's program for it; false where that can't be done. */
export async function openPath(path: string): Promise<boolean> {
  if (!isTauri()) return false
  const { openPath } = await import("@tauri-apps/plugin-opener")
  await openPath(path)
  return true
}

export { isTauri }
