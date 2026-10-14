// Spelling, checked in the window itself: nspell (a Hunspell-style checker)
// with the en_US dictionary from SCOWL, plus the resume folder's own word
// list (etc/dictionary.txt). Loaded apart from the rest of the window, as
// the dictionary is half a megabyte. (Its files are imported by their paths:
// the package only offers them to Node.)
import nspell from "nspell"
import aff from "../../node_modules/dictionary-en/index.aff?raw"
import dic from "../../node_modules/dictionary-en/index.dic?raw"

export type Miss = { start: number; end: number; word: string }

// Letters, with apostrophes inside ("don't", "Caterpillar's").
const WORD = /\p{L}+(?:['’]\p{L}+)*/gu
// Links, email addresses, and file or domain names aren't prose.
const NOT_PROSE = /:\/\/|@|\.\w{2,}(\/|$)/
const MAX_SUGGESTIONS = 6

export class Speller {
  private checker = nspell(aff, dic)
  private known = new Map<string, boolean>()

  constructor(words: string[]) {
    for (const word of words) this.add(word)
  }

  /** Takes a word as spelled right from now on. */
  add(word: string) {
    if (word.trim()) this.checker.add(word.trim())
    this.known.clear()
  }

  private correct(word: string) {
    let right = this.known.get(word)
    if (right === undefined) {
      const plain = word.replace(/’/g, "'")
      // A possessive of a word the dictionary has ("Caterpillar's") is as right as the word.
      right = this.checker.correct(plain) || (/'s$/i.test(plain) && this.checker.correct(plain.slice(0, -2)))
      this.known.set(word, right)
    }
    return right
  }

  /** The misspelled words in `text`. Acronyms in capitals, single letters, and anything in a link or beside a digit are let be. */
  check(text: string): Miss[] {
    const misses: Miss[] = []
    for (const match of text.matchAll(WORD)) {
      const word = match[0]
      const start = match.index
      const end = start + word.length
      if (word.length < 2 || word === word.toUpperCase()) continue
      // The run of text without spaces that the word is in: "example.com/about", "B2B".
      const from = text.lastIndexOf(" ", start) + 1
      const to = text.indexOf(" ", end) < 0 ? text.length : text.indexOf(" ", end)
      const token = text.slice(from, to)
      if (NOT_PROSE.test(token) || /\d/.test(token)) continue
      if (!this.correct(word)) misses.push({ start, end, word })
    }
    return misses
  }

  suggest(word: string) {
    return this.checker.suggest(word.replace(/’/g, "'")).slice(0, MAX_SUGGESTIONS)
  }
}
