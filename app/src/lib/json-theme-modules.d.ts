declare module "virtual:json-theme/*" {
  const theme: { render(resume: unknown): string | Promise<string> }
  export default theme
}

declare module "jsonresume-theme-even" {
  export function render(resume: unknown): string
}
