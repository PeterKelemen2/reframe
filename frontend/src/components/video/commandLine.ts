/**
 * What a piece of the command preview is, for its colour. `step` and `track` belong to a
 * header edit's line, which Reframe runs itself: `step` is its first word, not a program.
 */
export type TokenKind =
  | 'program'
  | 'step'
  | 'track'
  | 'option'
  | 'value'
  | 'path'
  | 'filter'
  | 'operator'
  | 'space'

export interface Token {
  /** As written in the command, quotes included: the tokens joined give the command back. */
  text: string
  kind: TokenKind
}

interface Word {
  text: string
  /** Without the shell's quoting. */
  value: string
}

const HEADER_EDIT = 'header_edit'
const TRACK = /^(video|audio|subtitle|\d+:)$/
const FILTER_OPTIONS = /^-(filter|vf|af|lavfi)(:|_complex$|$)/
const OPTION = /^-[A-Za-z_-]/
const PATH = /^(\/|~\/|\.\.?\/|[A-Za-z]:[\\/]|\\\\)/

/** Splits at unquoted whitespace; `'…'` is literal, `"…"` takes backslash escapes (POSIX and cmd). */
function split(command: string): (Word | string)[] {
  const parts: (Word | string)[] = []
  let index = 0
  while (index < command.length) {
    const space = /^\s+/.exec(command.slice(index))?.[0]
    if (space !== undefined) {
      parts.push(space)
      index += space.length
      continue
    }
    let value = ''
    const start = index
    while (index < command.length && !/\s/.test(command[index] as string)) {
      const char = command[index] as string
      if (char === "'") {
        const end = command.indexOf("'", index + 1)
        const close = end === -1 ? command.length : end
        value += command.slice(index + 1, close)
        index = close + 1
      } else if (char === '"') {
        index += 1
        while (index < command.length && command[index] !== '"') {
          if (command[index] === '\\' && index + 1 < command.length) index += 1
          value += command[index]
          index += 1
        }
        index += 1
      } else {
        value += char
        index += 1
      }
    }
    parts.push({ text: command.slice(start, Math.min(index, command.length)), value })
  }
  return parts
}

/**
 * A word of a header edit's line after its file: `audio 1:` names a track, `field=value` is a
 * field and its value, a word without `=` (`delete_name`) is a field alone.
 */
function headerEditTokens(word: Word): Token[] {
  if (TRACK.test(word.value)) return [{ text: word.text, kind: 'track' }]
  const equals = word.text.indexOf('=')
  if (equals === -1) return [{ text: word.text, kind: 'option' }]
  const tokens: Token[] = [
    { text: word.text.slice(0, equals + 1), kind: 'option' },
    { text: word.text.slice(equals + 1), kind: 'value' },
  ]
  return tokens.filter((token) => token.text !== '')
}

/**
 * The plan's shell-quoted command as coloured tokens: the program of each step, options, their
 * values, filter graphs (the value of `-filter…`, `-vf`, `-af`) and paths (`-i`'s value, a
 * value that starts like a path, a word that follows no option). A header edit's line is the
 * step's name, its file, then its tracks, fields and values.
 */
export function tokenize(command: string): Token[] {
  const tokens: Token[] = []
  let atProgram = true
  let option: string | null = null
  /** In a header edit's line: whether its file is the next word. */
  let headerEdit: { atFile: boolean } | null = null
  for (const part of split(command)) {
    if (typeof part === 'string') {
      tokens.push({ text: part, kind: 'space' })
      continue
    }
    let kind: TokenKind
    if (part.text === '&&') {
      kind = 'operator'
      atProgram = true
      option = null
      headerEdit = null
    } else if (atProgram && part.text === HEADER_EDIT) {
      kind = 'step'
      atProgram = false
      headerEdit = { atFile: true }
    } else if (headerEdit?.atFile) {
      kind = 'path'
      headerEdit.atFile = false
    } else if (headerEdit !== null) {
      tokens.push(...headerEditTokens(part))
      continue
    } else if (atProgram) {
      kind = 'program'
      atProgram = false
    } else if (OPTION.test(part.value)) {
      kind = 'option'
      option = part.value
    } else {
      if (option !== null && FILTER_OPTIONS.test(option)) kind = 'filter'
      else if (option === '-i' || option === null || PATH.test(part.value)) kind = 'path'
      else kind = 'value'
      option = null
    }
    tokens.push({ text: part.text, kind })
  }
  return tokens
}

/** The tokens one line per step: a line ends after `&&`, and the space after it is dropped. */
export function stepLines(tokens: readonly Token[]): Token[][] {
  const lines: Token[][] = [[]]
  for (const token of tokens) {
    const line = lines.at(-1) as Token[]
    if (token.kind === 'space' && line.length === 0 && lines.length > 1) continue
    line.push(token)
    if (token.kind === 'operator') lines.push([])
  }
  return lines.filter((line) => line.length > 0)
}
