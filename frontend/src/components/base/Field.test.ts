import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'

import type { JsonPatchOp, ValidationIssue } from '@/api/types'
import { REVEALED_CLASS } from '@/composables/useReveal'
import { sampleJob, samplePreset } from '@/editor/testing/samples'
import { type EditorTarget, type GroupScope, useEditorStore } from '@/stores/editor'
import { templateOfPreset } from '@/stores/presets'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import Field from './Field.vue'
import { mountBase } from './testing'
import type { FieldSlotProps } from './types'

function issue(severity: ValidationIssue['severity'], message: string, path = 'video.encoder') {
  return { severity, code: `test.${severity}`, path, message, fixes: [] }
}

const control = {
  default: (p: FieldSlotProps) =>
    h('input', { id: p.id, 'data-invalid': String(p.invalid), class: 'control' }),
}

function mountField(props: Record<string, unknown>) {
  return mountBase(Field, { props: { label: 'Encoder', ...props }, slots: control })
}

const QUALITY: JsonPatchOp = { op: 'replace', path: '/job/video/quality', value: 20 }

function groupTarget(scope: GroupScope, ops: JsonPatchOp[] = [QUALITY]): EditorTarget {
  return {
    kind: 'group',
    groupId: 'g1',
    sourceId: 'e2',
    job: sampleJob(),
    template: templateOfPreset(samplePreset()),
    presetId: null,
    overrides: { e2: ops },
    scope,
  }
}

/** A field of the shown file of a group, with the store's override actions replaced by spies. */
async function mountGroupField(path: string, scope: GroupScope = 'file') {
  const wrapper = mountField({ label: 'Quality', path })
  const editor = useEditorStore()
  editor.target = groupTarget(scope)
  const reset = vi.spyOn(editor, 'resetToGroup').mockImplementation(() => {
    editor.target = groupTarget(scope, [])
  })
  const apply = vi.spyOn(editor, 'applyToWholeGroup').mockImplementation(async () => {
    editor.target = groupTarget(scope, [])
  })
  await flushPromises()
  return { wrapper, editor, reset, apply }
}

async function chooseItem(label: string): Promise<void> {
  const item = [...document.querySelectorAll<HTMLElement>('[data-pc-section="item"]')].find((li) =>
    li.textContent?.includes(label),
  )
  item?.querySelector<HTMLElement>('a')?.click()
  await flushPromises()
}

afterEach(() => {
  document.body.replaceChildren()
})

describe('Field', () => {
  it("shows the store's issues for its path, most severe first, and marks an error invalid", async () => {
    const wrapper = mountField({ path: 'video.encoder' })
    useValidationStore().issues = [
      issue('warning', 'Slow'),
      issue('error', 'Not available'),
      issue('error', 'Elsewhere', 'audio[0].encoder'),
    ]
    await flushPromises()
    expect(wrapper.findAll('.rf-field__issue').map((li) => li.text())).toEqual([
      'Error: Not available',
      'Warning: Slow',
    ])
    expect(wrapper.classes()).toContain('rf-field--error')
    const input = wrapper.get('input.control')
    expect(input.attributes('data-invalid')).toBe('true')
    expect(wrapper.get('label').attributes('for')).toBe(input.attributes('id'))
    expect(input.attributes('aria-describedby')).toBe(wrapper.get('ul').attributes('id'))
  })

  it('shows its own issues instead of the store’s; a warning is not invalid', async () => {
    const wrapper = mountField({ path: 'video.encoder', issues: [issue('warning', 'Own')] })
    useValidationStore().issues = [issue('error', 'From the store')]
    await flushPromises()
    expect(wrapper.findAll('.rf-field__issue').map((li) => li.text())).toEqual(['Warning: Own'])
    expect(wrapper.classes()).toContain('rf-field--warning')
    expect(wrapper.get('input.control').attributes('data-invalid')).toBe('false')
  })

  it('drops the description and the outline when the issues go away', async () => {
    const wrapper = mountField({ path: 'video.encoder' })
    const validation = useValidationStore()
    validation.issues = [issue('error', 'Not available')]
    await flushPromises()
    expect(wrapper.get('input.control').attributes('aria-describedby')).toBeDefined()
    validation.issues = []
    await flushPromises()
    expect(wrapper.find('ul').exists()).toBe(false)
    expect(wrapper.get('input.control').attributes('aria-describedby')).toBeUndefined()
    expect(wrapper.classes()).not.toContain('rf-field--error')
  })

  it('shows the override dot only when overridden', async () => {
    const wrapper = mountField({})
    expect(wrapper.find('.rf-field__override').exists()).toBe(false)
    await wrapper.setProps({ overridden: true })
    expect(wrapper.get('.rf-field__override').attributes('aria-label')).toBe(
      'Differs from the group',
    )
  })

  it("shows a named dot in scope file when the shown file's override sets its path", async () => {
    const { wrapper } = await mountGroupField('video.quality')
    expect(wrapper.get('[data-action="override-menu"]').attributes('aria-label')).toBe(
      'Quality differs from the group',
    )
  })

  it('shows no dot for a path the override does not set, in scope group, or for a job', async () => {
    const { wrapper, editor } = await mountGroupField('video.encoder')
    expect(wrapper.find('[data-action="override-menu"]').exists()).toBe(false)
    const other = mountField({ label: 'Quality', path: 'video.quality' })
    editor.target = groupTarget('group')
    await flushPromises()
    expect(other.find('[data-action="override-menu"]').exists()).toBe(false)
    editor.target = { kind: 'job', sourceId: 'e2', job: sampleJob() }
    await flushPromises()
    expect(other.find('[data-action="override-menu"]').exists()).toBe(false)
  })

  it('resets the field to the group from its menu, and the focus goes back to the control', async () => {
    const { wrapper, reset, apply } = await mountGroupField('video.quality')
    await wrapper.get('[data-action="override-menu"]').trigger('click')
    await flushPromises()
    await chooseItem('Reset to group')
    expect(reset).toHaveBeenCalledWith('video.quality')
    expect(apply).not.toHaveBeenCalled()
    expect(wrapper.find('[data-action="override-menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(wrapper.get('input.control').element)
  })

  it('applies the value to the whole group from its menu, and the focus goes back to the control', async () => {
    const { wrapper, reset, apply } = await mountGroupField('video.quality')
    await wrapper.get('[data-action="override-menu"]').trigger('click')
    await flushPromises()
    await chooseItem('Apply to whole group')
    expect(apply).toHaveBeenCalledWith('video.quality')
    expect(reset).not.toHaveBeenCalled()
    expect(document.activeElement).toBe(wrapper.get('input.control').element)
  })

  it('offers no Apply to whole group for a per-file value, and says why', async () => {
    const { wrapper, editor, apply } = await mountGroupField('output.path')
    editor.target = groupTarget('file', [{ op: 'add', path: '/job/output/path', value: '/x.mkv' }])
    await flushPromises()
    await wrapper.get('[data-action="override-menu"]').trigger('click')
    await flushPromises()
    await chooseItem('Apply to whole group')
    expect(apply).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain(
      "Set per file: the group's template cannot hold it.",
    )
  })

  it('opens its help from a named button', async () => {
    const wrapper = mountField({ help: 'Lower is better.' })
    const button = wrapper.get('button[aria-label="About Encoder"]')
    expect(button.attributes('aria-expanded')).toBe('false')
    await button.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('Lower is better.')
    expect(button.attributes('aria-expanded')).toBe('true')
  })

  it('is the target of ui.reveal for its path', async () => {
    Element.prototype.scrollIntoView = vi.fn<() => void>()
    const wrapper = mountField({ path: 'video.encoder' })
    useUiStore().reveal('video.encoder')
    await flushPromises()
    await nextTick()
    expect(wrapper.classes()).toContain(REVEALED_CLASS)
    expect(document.activeElement).toBe(wrapper.get('input.control').element)
  })

  it('gives the focus to its control, not to the help button, when revealed', async () => {
    Element.prototype.scrollIntoView = vi.fn<() => void>()
    const wrapper = mountField({ path: 'video.encoder', help: 'Lower is better.' })
    useUiStore().reveal('video.encoder')
    await flushPromises()
    await nextTick()
    expect(document.activeElement).toBe(wrapper.get('input.control').element)
  })
})
