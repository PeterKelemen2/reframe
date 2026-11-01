import type { NamingVariable } from '@/stores/system'

/** Where the caret is inside a `{…}` that is being typed: its variable name or its format spec. */
export type Completion =
  | { kind: 'name'; start: number; end: number; query: string }
  | { kind: 'spec'; name: string; start: number; end: number; query: string }

const NAME_CHARS = /^[\w-]*$/
const NAME_CHAR = /[\w-]/

/**
 * What the caret at `caret` is completing, or `null` outside a variable. `{{` is a literal
 * brace; a second `{` before a `}` starts the variable again (the server reports the first one
 * as not closed).
 */
export function completionAt(text: string, caret: number): Completion | null {
  let open = -1
  for (let i = 0; i < caret; i += 1) {
    const char = text[i]
    if (open < 0) {
      if ((char === '{' || char === '}') && text[i + 1] === char && i + 1 < caret) i += 1
      else if (char === '{') open = i
    } else if (char === '}') open = -1
    else if (char === '{') open = i
  }
  if (open < 0) return null
  const body = text.slice(open + 1, caret)
  const colon = body.indexOf(':')
  if (colon < 0) {
    return NAME_CHARS.test(body) ? { kind: 'name', start: open + 1, end: caret, query: body } : null
  }
  return {
    kind: 'spec',
    name: body.slice(0, colon),
    start: open + 1 + colon + 1,
    end: caret,
    query: body.slice(colon + 1),
  }
}

/** The text after accepting `value` for `completion`, and where the caret goes (after the `}`). */
export function accept(
  text: string,
  completion: Completion,
  value: string,
): { text: string; caret: number } {
  let end = completion.end
  if (completion.kind === 'name') {
    while (end < text.length && NAME_CHAR.test(text[end] ?? '')) end += 1
  } else {
    while (end < text.length && text[end] !== '}' && text[end] !== '{') end += 1
  }
  const next = text[end]
  const keepsSpec = completion.kind === 'name' && next === ':'
  const closed = next === '}' || keepsSpec
  const before = text.slice(0, completion.start) + value
  const after = closed ? text.slice(end) : `}${text.slice(end)}`
  const caret = keepsSpec ? before.length : before.length + 1
  return { text: before + after, caret }
}

/** Variables for `query`: names that start with it first, then names that contain it. */
export function matchVariables(variables: NamingVariable[], query: string): NamingVariable[] {
  const wanted = query.toLowerCase()
  const starts = variables.filter((variable) => variable.name.toLowerCase().startsWith(wanted))
  const contains = variables.filter(
    (variable) =>
      !variable.name.toLowerCase().startsWith(wanted) &&
      variable.name.toLowerCase().includes(wanted),
  )
  return [...starts, ...contains]
}

/** A format spec the server's template parser takes for a kind of variable. */
export interface SpecSuggestion {
  spec: string
  /** Key of its description in `naming.spec`. */
  key: SpecKey
}

export type SpecKey =
  | 'pad2'
  | 'pad3'
  | 'upper'
  | 'lower'
  | 'title'
  | 'isoDate'
  | 'dotDate'
  | 'year'
  | 'time'
  | 'timeSeconds'

const SPECS: Record<NamingVariable['kind'], SpecSuggestion[]> = {
  number: [
    { spec: '02', key: 'pad2' },
    { spec: '03', key: 'pad3' },
  ],
  text: [
    { spec: 'upper', key: 'upper' },
    { spec: 'lower', key: 'lower' },
    { spec: 'title', key: 'title' },
  ],
  date: [
    { spec: '%Y-%m-%d', key: 'isoDate' },
    { spec: '%d.%m.%Y', key: 'dotDate' },
    { spec: '%Y', key: 'year' },
    { spec: '%H-%M', key: 'time' },
    { spec: '%H-%M-%S', key: 'timeSeconds' },
  ],
}

/** The specs for the variable `name` that start with `query`; none for an unknown variable. */
export function matchSpecs(
  variables: NamingVariable[],
  name: string,
  query: string,
): SpecSuggestion[] {
  const variable = variables.find((candidate) => candidate.name === name)
  if (variable === undefined) return []
  return SPECS[variable.kind].filter((suggestion) => suggestion.spec.startsWith(query))
}

/** `text` with `insertion` in place of the selection; the caret goes after it. */
export function insertAt(
  text: string,
  start: number,
  end: number,
  insertion: string,
): { text: string; caret: number } {
  return {
    text: text.slice(0, start) + insertion + text.slice(end),
    caret: start + insertion.length,
  }
}
