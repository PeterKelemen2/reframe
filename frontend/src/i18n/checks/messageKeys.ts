/** A literal message key in the code that the messages do not have. */
export interface MissingKey {
  file: string
  line: number
  key: string
  /** `missing`: no such key; `not a message`: the key names a group of messages. */
  problem: 'missing' | 'not a message'
}

/** `t('a.b')`, `$t("a.b", …)`, `te('a.b')`: a key that is the whole first argument. */
const KEY_CALL = /(?<![\w$])(\$?(?:t|te|tc|tm))\(\s*(['"`])([^'"`$\n]+)\2\s*[,)]/g
/** `<i18n-t keypath="a.b">`. */
const KEYPATH = /\bkeypath=(['"])([^'"]+)\1/g

export interface KeyUse {
  key: string
  line: number
  /** `tm` reads a group of messages; the others one message. */
  group: boolean
}

function lineAt(source: string, index: number): number {
  let line = 1
  for (let i = 0; i < index; i += 1) if (source.charCodeAt(i) === 10) line += 1
  return line
}

/** The literal message keys `source` uses. Keys built at run time are not seen. */
export function findKeyUses(source: string): KeyUse[] {
  const uses: KeyUse[] = []
  for (const match of source.matchAll(KEY_CALL)) {
    const [, call = '', , key = ''] = match
    uses.push({ key, line: lineAt(source, match.index), group: call.endsWith('tm') })
  }
  for (const match of source.matchAll(KEYPATH)) {
    uses.push({ key: match[2] ?? '', line: lineAt(source, match.index), group: false })
  }
  return uses
}

function lookup(messages: Record<string, unknown>, key: string): unknown {
  let node: unknown = messages
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null || !Object.hasOwn(node, part)) return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return node
}

/** Every literal key of `source` that `messages` (the English messages by area) lacks. */
export function findMissingKeys(
  source: string,
  file: string,
  messages: Record<string, unknown>,
): MissingKey[] {
  const missing: MissingKey[] = []
  for (const use of findKeyUses(source)) {
    const value = lookup(messages, use.key)
    if (value === undefined) {
      missing.push({ file, line: use.line, key: use.key, problem: 'missing' })
    } else if (use.group ? typeof value !== 'object' : typeof value !== 'string') {
      missing.push({ file, line: use.line, key: use.key, problem: 'not a message' })
    }
  }
  return missing
}
