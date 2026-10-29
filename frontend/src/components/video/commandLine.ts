/** What a piece of the command preview is, for its colour. */
export type TokenKind = 'program' | 'option' | 'value' | 'path' | 'filter' | 'operator' | 'space'

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
 * The plan's shell-quoted command as coloured tokens: the program of each step, options, their
 * values, filter graphs (the value of `-filter…`, `-vf`, `-af`) and paths (`-i`'s value, a
 * value that starts like a path, a word that follows no option).
 */
export function tokenize(command: string): Token[] {
  const tokens: Token[] = []
  let atProgram = true
  let option: string | null = null
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
