import { describe, expect, it } from 'vitest'

import type { FsRoot } from '@/api/types'

import { crumbsOf, extensionOf, folderOf, joinPath } from './paths'

const roots: FsRoot[] = [
  { name: 'media', path: '/srv/media', kind: 'media' },
  { name: 'Shows', path: '/srv/media/tv/shows', kind: 'media' },
  { name: 'output', path: '/srv/out', kind: 'output' },
]

describe('crumbsOf', () => {
  it('starts at the root that holds the folder, named as the root', () => {
    expect(crumbsOf('/srv/media/films/2024', roots)).toEqual([
      { label: 'media', path: '/srv/media' },
      { label: 'films', path: '/srv/media/films' },
      { label: '2024', path: '/srv/media/films/2024' },
    ])
  })

  it('takes the deepest root when roots are nested', () => {
    expect(crumbsOf('/srv/media/tv/shows/Show', roots)).toEqual([
      { label: 'Shows', path: '/srv/media/tv/shows' },
      { label: 'Show', path: '/srv/media/tv/shows/Show' },
    ])
  })

  it('does not take a root that only shares the start of a name', () => {
    expect(crumbsOf('/srv/media-old/x', roots)[0]).toEqual({ label: '/', path: '/' })
  })

  it('starts at the top of the file system outside every root', () => {
    expect(crumbsOf('/home/me', [])).toEqual([
      { label: '/', path: '/' },
      { label: 'home', path: '/home' },
      { label: 'me', path: '/home/me' },
    ])
  })

  it('follows a Windows server’s paths', () => {
    const drives: FsRoot[] = [{ name: 'C:\\', path: 'C:\\', kind: 'drive' }]
    expect(crumbsOf('C:\\Videos\\Show', drives)).toEqual([
      { label: 'C:\\', path: 'C:\\' },
      { label: 'Videos', path: 'C:\\Videos' },
      { label: 'Show', path: 'C:\\Videos\\Show' },
    ])
  })
})

describe('paths', () => {
  it('joins with the server’s separator, once', () => {
    expect(joinPath('/srv/out', 'a.mkv')).toBe('/srv/out/a.mkv')
    expect(joinPath('/', 'a.mkv')).toBe('/a.mkv')
    expect(joinPath('D:\\Out', 'a.mkv')).toBe('D:\\Out\\a.mkv')
  })

  it('gives the folder of a path, or null for a bare name', () => {
    expect(folderOf('/srv/out/a.mkv')).toBe('/srv/out')
    expect(folderOf('/a.mkv')).toBe('/')
    expect(folderOf('D:\\Out\\a.mkv')).toBe('D:\\Out')
    expect(folderOf('a.mkv')).toBeNull()
  })

  it('reads the extension in lower case; a hidden name has none', () => {
    expect(extensionOf('Movie.MKV')).toBe('mkv')
    expect(extensionOf('.hidden')).toBe('')
    expect(extensionOf('README')).toBe('')
  })
})
