// The preview of the resume's PDF: its pages, fitted to the panel's width,
// drawn with PDF.js. Links in it work, and the text of the field being
// edited is highlighted and scrolled to. It is for looking, not working in:
// File > Open PDF opens the PDF in the system's own viewer.
import * as React from "react"
import * as pdfjs from "pdfjs-dist"
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url"

import { isTauri, openUrl } from "@/lib/bridge"
import { plain } from "@/lib/model"

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const PHRASE_MIN = 4 // shorter text matches all over the PDF
// How much of the start of a field's text has to be found to place it: as much as can be, then less.
const PHRASE_STARTS = [40, 20, 10, PHRASE_MIN]
// What TeX prints in place of what was typed.
const PRINTED: Record<string, string> = { "’": "'", "‘": "'", "“": '"', "”": '"', "⋅": "·", "∙": "·", "−": "-" }

type Box = { left: number; top: number; width: number; height: number }
type PageText = { element: HTMLDivElement; chars: string; boxes: Box[]; owner: number[] }

/** Text for comparing: without spaces (the PDF's lines break anywhere), and with ligatures, curly quotes and the like as the letters typed. */
const squeeze = (text: string) => text.normalize("NFKC").replace(/\s+/g, "").replace(/[’‘“”⋅∙−]/g, (char) => PRINTED[char])

/** How many of the page's characters from `at` are the field's text `wanted`: all of it, where the page has it
 *  all. The page may hyphenate a word at the end of a line, and the field may have a bold mark left half typed. */
function matched(chars: string, at: number, wanted: string) {
  let on = at
  let next = 0
  while (next < wanted.length && on < chars.length) {
    if (chars[on] === wanted[next]) {
      on += 1
      next += 1
    } else if (chars[on] === "-" && chars[on + 1] === wanted[next]) {
      on += 1 // a hyphen the line break put in
    } else if (wanted[next] === "*") {
      next += 1 // a bold mark the PDF doesn't print
    } else {
      break
    }
  }
  return on - at
}

const PRINT_DPI = 300

/** Prints a PDF (as base64): its pages, drawn as images at PRINT_DPI, are laid out one to a sheet of paper for the web view's own print dialog. */
export async function printPdf(data: string) {
  const pdf = await pdfjs.getDocument({ data: Uint8Array.from(atob(data), (char) => char.charCodeAt(0)) }).promise
  const sheets = document.createElement("div")
  sheets.id = "print-pages"
  try {
    for (let number = 1; number <= pdf.numPages; number++) {
      const page = await pdf.getPage(number)
      const viewport = page.getViewport({ scale: PRINT_DPI / 72 })
      const canvas = document.createElement("canvas")
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)
      await page.render({ canvas, canvasContext: canvas.getContext("2d")!, viewport }).promise
      const sheet = document.createElement("img")
      sheet.src = canvas.toDataURL("image/png")
      await sheet.decode()
      sheets.append(sheet)
    }
    document.getElementById("print-pages")?.remove()
    document.body.append(sheets)
    // Taken away once printed (or the dialog is canceled), whichever way the web view says so.
    window.addEventListener("afterprint", () => sheets.remove(), { once: true })
    if (isTauri()) {
      const { invoke } = await import("@tauri-apps/api/core")
      await invoke("print") // the shell's own, as not every web view has window.print()
    } else {
      window.print()
    }
  } finally {
    void pdf.loadingTask.destroy()
  }
}

export function PdfView({ data, phrase }: { data: string | null; phrase: string }) {
  const scroller = React.useRef<HTMLDivElement>(null)
  const pages = React.useRef<PageText[]>([])
  const [width, setWidth] = React.useState(0)
  const [drawn, setDrawn] = React.useState(0)

  React.useEffect(() => {
    const element = scroller.current
    if (!element) return
    const observer = new ResizeObserver(() => setWidth(Math.floor(element.clientWidth / 20) * 20))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  React.useEffect(() => {
    const element = scroller.current
    if (!element || !data || width < 100) return
    let abandoned = false
    const task = pdfjs.getDocument({ data: Uint8Array.from(atob(data), (char) => char.charCodeAt(0)) })

    async function draw() {
      const pdf = await task.promise
      const built: PageText[] = []
      const frames: HTMLDivElement[] = []
      for (let number = 1; number <= pdf.numPages; number++) {
        const page = await pdf.getPage(number)
        const scale = (width - 16) / page.getViewport({ scale: 1 }).width
        const viewport = page.getViewport({ scale })
        const ratio = window.devicePixelRatio || 1
        const frame = document.createElement("div")
        frame.className = "relative mx-auto mb-3 bg-white shadow-md"
        frame.style.width = `${viewport.width}px`
        frame.style.height = `${viewport.height}px`
        const canvas = document.createElement("canvas")
        canvas.width = Math.floor(viewport.width * ratio)
        canvas.height = Math.floor(viewport.height * ratio)
        canvas.style.width = "100%"
        canvas.style.height = "100%"
        frame.append(canvas)
        await page.render({ canvas, canvasContext: canvas.getContext("2d")!, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] }).promise

        for (const annotation of await page.getAnnotations()) {
          if (annotation.subtype !== "Link" || !annotation.url) continue
          const [x1, y1] = viewport.convertToViewportPoint(annotation.rect[0], annotation.rect[1])
          const [x2, y2] = viewport.convertToViewportPoint(annotation.rect[2], annotation.rect[3])
          const link = document.createElement("a")
          link.href = annotation.url
          link.title = annotation.url
          link.className = "absolute cursor-pointer"
          Object.assign(link.style, { left: `${Math.min(x1, x2)}px`, top: `${Math.min(y1, y2)}px`, width: `${Math.abs(x2 - x1)}px`, height: `${Math.abs(y2 - y1)}px` })
          link.addEventListener("click", (event) => {
            event.preventDefault()
            void openUrl(annotation.url)
          })
          frame.append(link)
        }

        // Where each piece of the page's text is, to find a field's text among them.
        const text: PageText = { element: frame, chars: "", boxes: [], owner: [] }
        for (const item of (await page.getTextContent()).items) {
          if (!("str" in item) || !item.str.trim()) continue
          const [, , , , x, y] = pdfjs.Util.transform(viewport.transform, item.transform)
          const height = item.height * scale
          text.boxes.push({ left: x, top: y - height, width: item.width * scale, height: height * 1.15 })
          for (const char of squeeze(item.str)) {
            text.chars += char
            text.owner.push(text.boxes.length - 1)
          }
        }
        built.push(text)
        frames.push(frame)
        if (abandoned) return
      }
      // All at once, so the last PDF stays on show, and in place, until this one is ready.
      const at = element!.scrollTop
      element!.replaceChildren(...frames)
      element!.scrollTop = at
      pages.current = built
      setDrawn((count) => count + 1)
    }

    draw().catch(() => undefined)
    return () => {
      abandoned = true
      void task.destroy()
    }
  }, [data, width])

  React.useEffect(() => {
    for (const mark of scroller.current?.querySelectorAll("[data-highlight]") ?? []) mark.remove()
    const wanted = squeeze(plain(phrase))
    if (wanted.length < PHRASE_MIN) return
    // The place that has the most of the text, looked for by its start: all of it, or what comes before a hyphenated word.
    let best: { page: PageText; at: number; length: number } | null = null
    for (const start of PHRASE_STARTS) {
      if (wanted.length < start && start !== PHRASE_MIN) continue
      for (const page of pages.current) {
        for (let at = page.chars.indexOf(wanted.slice(0, start)); at >= 0; at = page.chars.indexOf(wanted.slice(0, start), at + 1)) {
          const length = matched(page.chars, at, wanted)
          if (!best || length > best.length) best = { page, at, length }
        }
      }
      if (best) break
    }
    if (best) {
      const { page, at, length } = best
      const boxes = new Set(page.owner.slice(at, at + length))
      let first: HTMLElement | null = null
      for (const index of boxes) {
        const box = page.boxes[index]
        const mark = document.createElement("div")
        mark.dataset.highlight = ""
        mark.className = "pointer-events-none absolute rounded-sm bg-yellow-300/45 mix-blend-multiply"
        Object.assign(mark.style, { left: `${box.left - 1}px`, top: `${box.top}px`, width: `${box.width + 2}px`, height: `${box.height}px` })
        page.element.append(mark)
        first ??= mark
      }
      first?.scrollIntoView({ block: "nearest", behavior: "smooth" })
    }
  }, [phrase, drawn])

  return (
    <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto rounded-lg bg-[var(--rw-deep)] p-2">
      {data ? null : <div className="p-6 text-center text-sm text-muted-foreground">No PDF yet. Build the resume to see it here.</div>}
    </div>
  )
}
