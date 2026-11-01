/** Where the web build keeps the tab's token: the address fragment once, then `sessionStorage`. */

const STORAGE_KEY = 'reframe.token'

/**
 * The `token` of the address fragment (`#token=…`), removed from the address and from the
 * entry in the browser history. `null` when the fragment has none.
 */
export function takeFragmentToken(
  where: Location = window.location,
  history: History = window.history,
): string | null {
  const params = new URLSearchParams(where.hash.slice(1))
  const token = params.get('token')
  if (token === null) return null
  params.delete('token')
  const rest = params.toString()
  history.replaceState(
    history.state,
    '',
    `${where.pathname}${where.search}${rest ? `#${rest}` : ''}`,
  )
  return token || null
}

// Storage can be missing or throw (a private window, blocked site data): the token then lasts
// until the page is reloaded.
export function storedToken(storage: () => Storage = () => window.sessionStorage): string | null {
  try {
    return storage().getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function storeToken(
  token: string | null,
  storage: () => Storage = () => window.sessionStorage,
): void {
  try {
    if (token === null) storage().removeItem(STORAGE_KEY)
    else storage().setItem(STORAGE_KEY, token)
  } catch {
    // Kept in memory only.
  }
}
