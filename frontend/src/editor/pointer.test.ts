import { describe, expect, it } from 'vitest'

import { pathOf, pointerOf, tokensOf, valueAt } from './pointer'

describe('validation paths and JSON pointers', () => {
  it.each([
    ['video.encoder', '/video/encoder'],
    ['audio[2].encoder', '/audio/2/encoder'],
    ['audio[12]', '/audio/12'],
    ['subtitles[0].metadata.language', '/subtitles/0/metadata/language'],
    ['video.advanced.rc-lookahead', '/video/advanced/rc-lookahead'],
    ['filters.deinterlace', '/filters/deinterlace'],
  ])('%s is the pointer %s and back', (path, pointer) => {
    expect(pointerOf(path)).toBe(pointer)
    expect(pathOf(pointer)).toBe(path)
  })

  it('escapes / and ~ in a key as the server does', () => {
    expect(pointerOf('tags.a/b~c')).toBe('/tags/a~1b~0c')
    expect(pathOf('/tags/a~1b~0c')).toBe('tags.a/b~c')
  })

  it('reads an index with a leading zero as an object key', () => {
    expect(pathOf('/video/advanced/01')).toBe('video.advanced.01')
  })

  it('maps the whole document to the empty path', () => {
    expect(pointerOf('')).toBe('')
    expect(pathOf('')).toBe('')
  })

  it('refuses a pointer without its leading slash', () => {
    expect(() => tokensOf('video/encoder')).toThrow(/Not a JSON pointer/)
  })
})

describe('valueAt', () => {
  const document = {
    video: { encoder: 'libx265', advanced: { 'a/b': 1 } },
    audio: [{ bitrate: 160 }],
  }

  it('reads members and list items', () => {
    expect(valueAt(document, '/video/encoder')).toBe('libx265')
    expect(valueAt(document, '/audio/0/bitrate')).toBe(160)
    expect(valueAt(document, '/video/advanced/a~1b')).toBe(1)
    expect(valueAt(document, '')).toBe(document)
  })

  it('gives undefined for what is not there', () => {
    expect(valueAt(document, '/audio/1/bitrate')).toBeUndefined()
    expect(valueAt(document, '/video/encoder/name')).toBeUndefined()
    expect(valueAt(document, '/toString')).toBeUndefined()
  })
})
