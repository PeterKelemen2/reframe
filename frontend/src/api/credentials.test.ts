import { afterEach, describe, expect, it } from 'vitest'

import { storedToken, storeToken, takeFragmentToken } from './credentials'

function broken(): Storage {
  throw new DOMException('denied', 'SecurityError')
}

describe('the tab token', () => {
  afterEach(() => {
    history.replaceState(null, '', '/')
    sessionStorage.clear()
  })

  it('takes the token from the address fragment and removes it from the address', () => {
    history.replaceState({ router: 1 }, '', '/queue?x=1#token=abc%2Fdef')
    expect(takeFragmentToken()).toBe('abc/def')
    expect(`${location.pathname}${location.search}${location.hash}`).toBe('/queue?x=1')
    expect(history.state).toEqual({ router: 1 })
  })

  it('keeps the rest of the fragment', () => {
    history.replaceState(null, '', '/#token=abc&tab=video')
    expect(takeFragmentToken()).toBe('abc')
    expect(location.hash).toBe('#tab=video')
  })

  it('leaves an address without a token alone', () => {
    history.replaceState(null, '', '/#tab=video')
    expect(takeFragmentToken()).toBeNull()
    expect(location.hash).toBe('#tab=video')
  })

  it('keeps the token in the tab storage, and works without one', () => {
    storeToken('abc')
    expect(sessionStorage.getItem('reframe.token')).toBe('abc')
    expect(storedToken()).toBe('abc')
    storeToken(null)
    expect(storedToken()).toBeNull()

    expect(() => storeToken('abc', broken)).not.toThrow()
    expect(storedToken(broken)).toBeNull()
  })
})
