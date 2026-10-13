declare module "nspell" {
  type NSpell = { correct(word: string): boolean; suggest(word: string): string[]; add(word: string): NSpell }
  export default function nspell(aff: string, dic: string): NSpell
}
declare module "*?raw" {
  const text: string
  export default text
}
