import { describe, expect, it } from 'vitest'

import { folderOf, joinPath, nextOutputPath } from './path'

describe('folderOf', () => {
  it('cuts the relative name off the path, subfolders included', () => {
    expect(folderOf('/out/Show/Season 03/Show.S03E02.mkv', 'Show/Season 03/Show.S03E02.mkv')).toBe(
      '/out',
    )
  })

  it('finds the folder when only the extension changed', () => {
    expect(folderOf('/out/Show/Show.S03E02.mkv', 'Show/Show.S03E02.mp4')).toBe('/out')
  })

  it("takes a path that is not the template's name as a file in its folder", () => {
    expect(folderOf('/elsewhere/picked.mkv', 'Show/Show.S03E02.mkv')).toBe('/elsewhere')
  })

  it('has no folder without a path', () => {
    expect(folderOf(null, 'a.mkv')).toBeNull()
  })

  it('reads a Windows path with its own separator', () => {
    expect(folderOf('D:\\out\\Show\\x.mkv', 'Show/x.mkv')).toBe('D:\\out')
  })
})

describe('joinPath', () => {
  it("joins with the folder's separator", () => {
    expect(joinPath('D:\\out\\', 'Show/x.mkv')).toBe('D:\\out\\Show\\x.mkv')
    expect(joinPath('/out', 'Show/x.mkv')).toBe('/out/Show/x.mkv')
  })
})

describe('nextOutputPath', () => {
  it("keeps the job's own folder for the new name", () => {
    expect(
      nextOutputPath('/picked/Old.mkv', 'Old.mkv', {
        relative_path: 'New.mkv',
        path: '/out/New.mkv',
      }),
    ).toBe('/picked/New.mkv')
  })

  it("takes the server's path when the job has none", () => {
    expect(nextOutputPath(null, null, { relative_path: 'New.mkv', path: '/out/New.mkv' })).toBe(
      '/out/New.mkv',
    )
  })
})
