import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { probedSource } from '@/components/tracks/testing'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'

import { useJobSource } from './useJobSource'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useJobSource', () => {
  it("gives a group's shown file as the job's source", () => {
    const source = probedSource('multitrack')
    useSourcesStore().entries = [
      { id: 'e1', path: '/media/e1.mkv', source: null },
      { id: 'e2', path: '/media/e2.mkv', source },
    ]
    useEditorStore().target = {
      kind: 'group',
      groupId: 'g1',
      sourceId: 'e2',
      job: sampleJob(),
      template: templateOfPreset(samplePreset()),
      presetId: null,
      overrides: {},
      scope: 'group',
    }
    const found = useJobSource()
    expect(found.sourceId.value).toBe('e2')
    expect(found.source.value).toEqual(source)
  })
})
