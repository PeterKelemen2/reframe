/**
 * What a skeleton stub does until its owner builds it: fail loudly, naming what is missing.
 * The arguments are the stub's own, so that its signature stays the contract's.
 */
export function notBuilt(what: string, ...args: unknown[]): never {
  throw new Error(`${what} is not built yet (${args.length} arguments)`)
}
