import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import AudioTab from '@/components/editor/tabs/AudioTab.vue'
import SubtitlesTab from '@/components/editor/tabs/SubtitlesTab.vue'
import LanguagePicker from '@/components/language/LanguagePicker.vue'
import { issue } from '@/editor/testing/samples'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { mountEditor, prepareDom, unmountAll } from './editorTesting'
import TrackMetadataEditor from './TrackMetadataEditor.vue'

beforeAll(prepareDom)
afterEach(unmountAll)

const block = (wrapper: VueWrapper, path: string) => wrapper.find(`[data-metadata="${path}"]`)

function picker(wrapper: VueWrapper, path: string) {
  return wrapper
    .find(`.rf-field[data-path="${path}.language"]`)
    .findComponent(LanguagePicker) as unknown as VueWrapper
}

const pickerProp = (wrapper: VueWrapper, path: string, name: string) =>
  (picker(wrapper, path).props() as Record<string, unknown>)[name]

function menuItem(label: string): HTMLElement | null | undefined {
  return [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
    .find((element) => element.textContent?.trim().startsWith(label) === true)
    ?.querySelector<HTMLElement>('.p-menu-item-content')
}

describe('the metadata block of an output track', () => {
  it('sets the language through the picker, one undo step; None keeps the source language', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    picker(wrapper, 'audio[1].metadata').vm.$emit('update:modelValue', 'hu')
    expect(editor.job?.audio?.[1]?.metadata?.language).toBe('hu')
    picker(wrapper, 'audio[1].metadata').vm.$emit('update:modelValue', null)
    expect(editor.job?.audio?.[1]?.metadata?.language).toBeNull()
    editor.undo()
    expect(editor.job?.audio?.[1]?.metadata?.language).toBe('hu')
    editor.undo()
    expect(editor.job?.audio?.[1]?.metadata?.language).toBe('en')
  })

  it("offers the job's container to the picker, so the code shown is the one written", async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    expect(pickerProp(wrapper, 'audio[0].metadata', 'container')).toBe('mkv')
    editor.set('/output/container', 'mp4')
    await nextTick()
    expect(pickerProp(wrapper, 'audio[0].metadata', 'container')).toBe('mp4')
  })

  it('makes typing a name one undo step, ended when the field is left', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    const input = wrapper.find('.rf-field[data-path="audio[2].metadata.name"] input')
    await input.setValue('Commentary')
    await input.setValue('Commentary with the director')
    await input.trigger('blur')
    await input.setValue('')
    expect(editor.job?.audio?.[2]?.metadata?.name).toBe('')
    editor.undo()
    expect(editor.job?.audio?.[2]?.metadata?.name).toBe('Commentary with the director')
    editor.undo()
    expect(editor.job?.audio?.[2]?.metadata?.name).toBe("Director's Commentary")
  })

  it("fills the name from the track's values, and keeps or drops the source title", async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    await wrapper.find('[data-path="audio[0]"] [data-action="name-menu"]').trigger('click')
    await nextTick()
    menuItem('Japanese 2.0 AAC')?.click()
    expect(editor.job?.audio?.[0]?.metadata?.name).toBe('Japanese 2.0 AAC')
    await wrapper.find('[data-path="audio[0]"] [data-action="name-menu"]').trigger('click')
    await nextTick()
    menuItem('Keep the source title')?.click()
    expect(editor.job?.audio?.[0]?.metadata?.name).toBeNull()
    await wrapper.find('[data-path="audio[0]"] [data-action="name-menu"]').trigger('click')
    await nextTick()
    menuItem('Write no title')?.click()
    expect(editor.job?.audio?.[0]?.metadata?.name).toBe('')
  })

  it('shows which name null and "" stand for', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    const input = () => wrapper.find('.rf-field[data-path="audio[2].metadata.name"] input')
    editor.set('/audio/2/metadata/name', null)
    await nextTick()
    expect(input().attributes('placeholder')).toBe("As the source: Director's Commentary")
    editor.set('/audio/2/metadata/name', '')
    await nextTick()
    expect(input().attributes('placeholder')).toBe('No title')
  })

  it('toggles each of the six flags, one undo step each', async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    const flags = [
      'default',
      'forced',
      'commentary',
      'hearing_impaired',
      'visual_impaired',
      'original',
    ] as const
    await flags.reduce(
      (before, flag) =>
        before.then(() =>
          wrapper
            .find(`.rf-field[data-path="audio[1].metadata.${flag}"] input`)
            .setValue(!editor.job?.audio?.[1]?.metadata?.[flag]),
        ),
      Promise.resolve(),
    )
    expect(editor.job?.audio?.[1]?.metadata).toMatchObject({
      default: true,
      forced: true,
      commentary: true,
      hearing_impaired: true,
      visual_impaired: true,
      original: true,
    })
    editor.undo()
    expect(editor.job?.audio?.[1]?.metadata).toMatchObject({
      visual_impaired: true,
      original: false,
    })
  })

  it("shows a flag's issue at the flag, with its fix as a button", async () => {
    const { wrapper, editor } = await mountEditor(AudioTab)
    editor.set('/audio/1/metadata/default', true)
    useValidationStore().issues = [
      issue('metadata.several_defaults', 'audio[1].metadata.default', 'warning', [
        {
          label: 'Keep only audio track 1 default',
          target: 'job',
          patch: [{ op: 'replace', path: '/audio/1/metadata/default', value: false }],
        },
      ]),
    ]
    await nextTick()
    const row = wrapper.find('[data-path="audio[1]"]')
    expect(row.find('.rf-field[data-path="audio[1].metadata.default"]').text()).toContain(
      'metadata.several_defaults',
    )
    expect(row.find('.track-row__issues').exists()).toBe(false)
    const fix = row.find('[data-role="fixes"] button')
    expect(fix.text()).toBe('Keep only audio track 1 default')
    await fix.trigger('click')
    await flushPromises()
    expect(editor.job?.audio?.[1]?.metadata?.default).toBe(false)
  })

  it('is folded in a row, and opens when one of its fields has an issue', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    const body = () => block(wrapper, 'audio[0].metadata').find('.track-metadata__body')
    expect(body().isVisible()).toBe(false)
    expect(block(wrapper, 'audio[0].metadata').find('[data-role="summary"]').text()).toBe(
      'Japanese · “Japanese 5.1” · Default',
    )
    useValidationStore().issues = [
      issue('tool.mkvpropedit_missing', 'audio[0].metadata.original', 'warning'),
    ]
    await nextTick()
    expect(body().isVisible()).toBe(true)
  })

  it('opens when a link to one of its fields lands on it', async () => {
    const { wrapper } = await mountEditor(AudioTab)
    const body = () => block(wrapper, 'audio[1].metadata').find('.track-metadata__body')
    useUiStore().reveal('audio[1].metadata.commentary')
    await flushPromises()
    expect(body().isVisible()).toBe(true)
    expect(document.activeElement?.closest('[data-path="audio[1].metadata.commentary"]')).not.toBe(
      null,
    )
  })

  it('writes the video track at /video/metadata', async () => {
    const { wrapper, editor } = await mountEditor(TrackMetadataEditor, {
      props: { list: 'video' },
    })
    await wrapper.find('.rf-field[data-path="video.metadata.original"] input').setValue(true)
    picker(wrapper, 'video.metadata').vm.$emit('update:modelValue', 'ja')
    expect(editor.job?.video?.metadata).toMatchObject({ original: true, language: 'ja' })
    expect(wrapper.find('[data-action="metadata-toggle"]').exists()).toBe(false)
  })
})

describe('the metadata block of a subtitle track', () => {
  it('is off for a burned-in track, which has no track to write it to', async () => {
    const { wrapper } = await mountEditor(SubtitlesTab, {
      job: (job) => (job.subtitles![0]!.action = 'burn'),
    })
    const toggle = wrapper.find('.rf-field[data-path="subtitles[0].metadata.forced"] input')
    expect(toggle.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-note="burned"]').exists()).toBe(true)
  })

  it("sets an external file's language and flags on the file too", async () => {
    const { wrapper, editor } = await mountEditor(SubtitlesTab, {
      job: (job) =>
        (job.subtitles = [
          {
            action: 'copy',
            convert_to: null,
            forced_only: false,
            source: { path: '/media/a.srt', language: null, name: null, offset_ms: 0 },
            metadata: {
              default: false,
              forced: false,
              commentary: false,
              hearing_impaired: false,
              visual_impaired: false,
              original: false,
              language: null,
              name: null,
            },
          },
        ]),
      server: (server) =>
        server.on('POST /api/subtitles/inspect', {
          path: '/media/a.srt',
          format: 'subrip',
          bitmap: false,
          charset: 'UTF-8',
          events: 3,
          issues: [],
        }),
    })
    picker(wrapper, 'subtitles[0].metadata').vm.$emit('update:modelValue', 'pt-BR')
    await wrapper
      .find('.rf-field[data-path="subtitles[0].metadata.hearing_impaired"] input')
      .setValue(true)
    const track = editor.job?.subtitles?.[0]
    expect(track?.metadata).toMatchObject({ language: 'pt-BR', hearing_impaired: true })
    expect(track?.source).toMatchObject({
      language: 'pt-BR',
      flags: { hearing_impaired: true, default: false },
    })
    expect(pickerProp(wrapper, 'subtitles[0].metadata', 'noneLabel')).toBe(
      'Not set (written as und)',
    )
  })
})
