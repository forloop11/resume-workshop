// The editor's color themes, which the backend hands over from
// backend/themes.py: each names a color for every role the look uses. They
// are applied as the CSS variables the shadcn/ui components draw with, plus
// a few of the editor's own (--rw-*).
export type Theme = Record<string, string>

const VARIABLES: Record<string, string> = {
  "--background": "window", "--foreground": "text", "--card": "card", "--card-foreground": "text",
  "--popover": "bar", "--popover-foreground": "text", "--primary": "accent", "--primary-foreground": "on-accent",
  "--secondary": "line", "--secondary-foreground": "text", "--muted": "bar", "--muted-foreground": "muted",
  "--accent": "pressed", "--accent-foreground": "text", "--destructive": "error", "--border": "line",
  "--input": "line", "--ring": "accent",
  "--rw-deep": "deep", "--rw-bar": "bar", "--rw-window-end": "window-end", "--rw-ok": "ok", "--rw-warning": "warning", "--rw-link": "link",
  "--rw-hover": "hover", "--rw-invalid": "invalid-fill", "--rw-faint": "faint", "--rw-selection": "selection",
}

function isDark(hex: string) {
  const [r, g, b] = [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16))
  return 0.299 * r + 0.587 * g + 0.114 * b < 128
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement
  for (const [variable, role] of Object.entries(VARIABLES)) root.style.setProperty(variable, theme[role])
  root.classList.toggle("dark", isDark(theme.window))
}
