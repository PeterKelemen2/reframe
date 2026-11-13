import { expect, test } from '../support/test'
import { asKnown, checkScreen, compare, preparePage } from './gate'
import { known as pictureKnown } from './known/picture'
import { known as shellKnown } from './known/shell'
import { known as tracksKnown } from './known/tracks'
import { screens as pictureScreens } from './screens/picture'
import { screens as shellScreens } from './screens/shell'
import { screens as tracksScreens } from './screens/tracks'
import type { Browser } from './types'

const SCREENS = [...shellScreens, ...pictureScreens, ...tracksScreens]
const KNOWN = [...shellKnown, ...pictureKnown, ...tracksKnown]

test('every screen id is unique and every known entry names a screen', () => {
  const ids = SCREENS.map((screen) => screen.id)
  expect(ids.filter((id, index) => ids.indexOf(id) !== index)).toEqual([])
  const areaOf = new Map(SCREENS.map((screen) => [screen.id, screen.area]))
  const lists = { shell: shellKnown, picture: pictureKnown, tracks: tracksKnown }
  const misplaced = Object.entries(lists).flatMap(([area, entries]) =>
    entries.filter((entry) => areaOf.get(entry.screen) !== area).map((entry) => entry.screen),
  )
  expect(misplaced, 'known entries of a screen another area owns, or of no screen').toEqual([])
})

for (const screen of SCREENS) {
  test(`a11y gate: ${screen.area} ${screen.id}`, async ({ page }, info) => {
    test.setTimeout(300_000)
    await preparePage(page)
    await screen.setup(page)
    const found = await checkScreen(page, screen)
    const { unlisted, gone } = compare(
      found,
      KNOWN.filter((entry) => entry.screen === screen.id),
      info.project.name as Browser,
    )
    expect(unlisted.map(asKnown), `${screen.id}: findings not in known/${screen.area}.ts`).toEqual(
      [],
    )
    expect(
      gone.map((entry) => JSON.stringify(entry)),
      `${screen.id}: known findings that no longer happen (remove them from known/${screen.area}.ts)`,
    ).toEqual([])
  })
}
