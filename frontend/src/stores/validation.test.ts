import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { ref } from 'vue'

import { issue } from '@/editor/testing/samples'

import { useValidationStore } from './validation'

describe('the validation store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('finds the issues at a path, most severe first', () => {
    const validation = useValidationStore()
    const info = issue('audio.passthru_fallback', 'audio[1].encoder', 'info')
    const error = issue('encoder.unavailable', 'audio[1].encoder')
    const warning = issue('metadata.several_defaults', 'audio[1].encoder', 'warning')
    validation.issues = [info, issue('encoder.unavailable', 'video.encoder'), error, warning]
    expect(validation.issuesFor('audio[1].encoder')).toEqual([error, warning, info])
  })

  it("finds a field's own issues and, nested, those below it but not a sibling's", () => {
    const validation = useValidationStore()
    const track = issue('audio.track_missing', 'audio[1]')
    const bitrate = issue('audio.bitrate_out_of_range', 'audio[1].bitrate', 'info')
    const other = issue('audio.bitrate_out_of_range', 'audio[10].bitrate', 'info')
    const advanced = issue('encoder.option_unknown', 'video.advanced.rc-lookahead')
    const defaults = issue('defaults.no_listed_language', 'audio_defaults.selection.no_match')
    validation.issues = [track, bitrate, other, advanced, defaults]
    expect(validation.issuesFor('audio[1]')).toEqual([track])
    expect(validation.issuesFor('audio[1]', { nested: true })).toEqual([track, bitrate])
    expect(validation.issuesFor('audio', { nested: true })).toEqual([track, bitrate, other])
    expect(validation.issuesFor('video.advanced', { nested: true })).toEqual([advanced])
  })

  it('counts the issues by severity; an error blocks', () => {
    const validation = useValidationStore()
    validation.issues = [issue('a', 'x', 'warning'), issue('b', 'y', 'info')]
    expect(validation.counts).toEqual({ error: 0, warning: 1, info: 1 })
    expect(validation.hasErrors).toBe(false)
    validation.issues = [...validation.issues, issue('c', 'z')]
    expect(validation.hasErrors).toBe(true)
  })

  it("keeps the client's own issues beside the server's, which replace only their own", () => {
    const validation = useValidationStore()
    const found = ref([issue('dimensions.crop_frames_disagree', 'dimensions.crop', 'warning')])
    validation.addLocal('crop', () => found.value)
    validation.issues = [issue('a', 'x', 'info')]
    expect(validation.issues.map((each) => each.code)).toEqual([
      'a',
      'dimensions.crop_frames_disagree',
    ])
    expect(validation.issuesFor('dimensions.crop')).toEqual(found.value)
    validation.issues = []
    expect(validation.counts).toEqual({ error: 0, warning: 1, info: 0 })
    found.value = []
    expect(validation.issues).toEqual([])
  })
})
