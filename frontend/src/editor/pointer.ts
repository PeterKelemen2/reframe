/** A list index in a JSON pointer: `0`, `12`; `01` is an object key. */
const INDEX = /^(0|[1-9]\d*)$/

function escapeToken(token: string): string {
  return token.replaceAll('~', '~0').replaceAll('/', '~1')
}

function unescapeToken(token: string): string {
  return token.replaceAll('~1', '/').replaceAll('~0', '~')
}

/** The tokens of an RFC 6901 pointer; `''` is the whole document. */
export function tokensOf(pointer: string): string[] {
  if (pointer === '') return []
  if (!pointer.startsWith('/')) throw new Error(`Not a JSON pointer: ${JSON.stringify(pointer)}`)
  return pointer.slice(1).split('/').map(unescapeToken)
}

/**
 * `audio[2].encoder` (a validation path) → `/audio/2/encoder`, the same pointer as the server's
 * fixes use for that field.
 */
export function pointerOf(path: string): string {
  return path
    .replaceAll(/\[(\d+)\]/g, '.$1')
    .split('.')
    .filter((part) => part !== '')
    .map((part) => `/${escapeToken(part)}`)
    .join('')
}

/** `/audio/2/encoder` → `audio[2].encoder`. */
export function pathOf(pointer: string): string {
  let path = ''
  for (const token of tokensOf(pointer)) {
    if (INDEX.test(token)) path += `[${token}]`
    else path += path === '' ? token : `.${token}`
  }
  return path
}

/** The value at `pointer` in `document`, or `undefined` when there is none. */
export function valueAt(document: unknown, pointer: string): unknown {
  let node = document
  for (const token of tokensOf(pointer)) {
    if (typeof node !== 'object' || node === null || !Object.hasOwn(node, token)) return undefined
    node = (node as Record<string, unknown>)[token]
  }
  return node
}
