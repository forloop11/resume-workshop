// File > Page Setup: the page margins in input/geometry.yaml. The preview
// follows the dialog as values change; OK writes the file, keeping its
// comments and any length that wasn't changed as it was written.
import * as React from "react"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { GEOMETRY_FIELDS, MAXIMUM_INCHES, parseGeometry, UNITS, updateGeometry, type Lengths } from "@/lib/model"

export function PageSetup({ text, onChange, onClose }: {
  text: string
  /** The file as the dialog has it, for the preview to follow. */
  onChange(text: string): void
  /** OK, with the file to write; or Cancel, with null. */
  onClose(text: string | null): void
}) {
  const initial = React.useMemo(() => parseGeometry(text), [text])
  const [lengths, setLengths] = React.useState<Lengths>(initial)
  // Only what was changed is rewritten.
  const edited = () => updateGeometry(text, Object.fromEntries(Object.entries(lengths).filter(([name, [number, unit]]) => number !== initial[name][0] || unit !== initial[name][1])))

  function set(name: string, number: number, unit: string) {
    const next = { ...lengths, [name]: [number, unit] as [number, string] }
    setLengths(next)
    onChange(updateGeometry(text, Object.fromEntries(Object.entries(next).filter(([key, [value, valueUnit]]) => value !== initial[key][0] || valueUnit !== initial[key][1]))))
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose(null)}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Page Setup</DialogTitle>
          <DialogDescription>The page's margins. The paper is US Letter, set in input/format.tex.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          {GEOMETRY_FIELDS.map(([name, label]) => {
            const [number, unit] = lengths[name]
            const [perInch, decimals] = UNITS[unit]
            return (
              <label key={name} className="flex items-center gap-2 text-sm">
                <span className="flex-1">{label}</span>
                <input
                  type="number" min={0} max={MAXIMUM_INCHES * perInch} step={10 ** -decimals} value={Number(number.toFixed(decimals))}
                  onChange={(event) => set(name, Math.min(Math.max(Number(event.target.value) || 0, 0), MAXIMUM_INCHES * perInch), unit)}
                  className="w-24 rounded-md border border-input bg-[var(--rw-deep)] px-2 py-1 text-right outline-none focus-visible:border-ring"
                />
                <select
                  value={unit} onChange={(event) => set(name, (number / perInch) * UNITS[event.target.value][0], event.target.value)}
                  className="rounded-md border border-input bg-[var(--rw-deep)] px-1 py-1 outline-none"
                >
                  {Object.keys(UNITS).map((option) => <option key={option}>{option}</option>)}
                </select>
              </label>
            )
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onClose(null)}>Cancel</Button>
          <Button onClick={() => onClose(edited())}>OK</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
