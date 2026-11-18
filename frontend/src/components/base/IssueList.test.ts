import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Fix, ValidationIssue } from '@/api/types'
import { mountShell } from '@/components/shell/testing'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import IssueList from './IssueList.vue'
import { mountBase } from './testing'

const useFallback: Fix = { label: 'Use libx264', patch: [], target: 'job' }
const chooseEncoder: Fix = { label: 'Choose encoder', patch: [], target: 'job' }

const ISSUES: ValidationIssue[] = [
  { severity: 'info', code: 'i', path: 'video.frame_rate', message: 'Variable frame rate' },
  { severity: 'warning', code: 'w', path: '', message: 'Low bitrate' },
  {
    severity: 'error',
    code: 'e',
    path: 'video.encoder',
    message: 'Encoder missing',
    fixes: [useFallback, chooseEncoder],
  },
]

function setup(issues = ISSUES) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const editor = useEditorStore()
  const ui = useUiStore()
  const wrapper = mountBase(IssueList, { props: { issues }, pinia })
  return { wrapper, editor, ui }
}

afterEach(() => {
  document.body.replaceChildren()
})

describe('IssueList', () => {
  it('lists the issues most severe first', () => {
    const { wrapper } = setup()
    expect(wrapper.findAll('.rf-issue__message').map((m) => m.text())).toEqual([
      'Encoder missing',
      'Low bitrate',
      'Variable frame rate',
    ])
  })

  it('applies the fix that is clicked', async () => {
    const { wrapper, editor } = setup()
    editor.applyFix = vi.fn<(fix: Fix) => Promise<void>>(async () => {})
    await wrapper.findAll('.rf-issue__fix')[1]?.trigger('click')
    expect(editor.applyFix).toHaveBeenCalledExactlyOnceWith(chooseEncoder)
  })

  it('blocks the other fixes while one is being applied', async () => {
    const { wrapper, editor } = setup()
    let finish: (() => void) | undefined
    editor.applyFix = vi.fn<(fix: Fix) => Promise<void>>(
      () => new Promise<void>((resolve) => (finish = resolve)),
    )
    const [first, second] = wrapper.findAll('.rf-issue__fix')
    await first?.trigger('click')
    expect(second?.attributes('disabled')).toBeDefined()
    await second?.trigger('click')
    expect(editor.applyFix).toHaveBeenCalledTimes(1)
    finish?.()
    await flushPromises()
    expect(second?.attributes('disabled')).toBeUndefined()
  })

  it('links an issue with a path to its field, and only those', async () => {
    const { wrapper, ui } = setup()
    ui.reveal = vi.fn<(path: string) => void>()
    const items = wrapper.findAll('.rf-issue')
    expect(items.map((item) => item.find('.rf-issue__reveal').exists())).toEqual([
      true,
      false,
      true,
    ])
    await items[0]?.get('.rf-issue__reveal').trigger('click')
    expect(ui.reveal).toHaveBeenCalledExactlyOnceWith('video.encoder')
  })

  it('says so when there are no issues', () => {
    const { wrapper } = setup([])
    expect(wrapper.find('ul').exists()).toBe(false)
    expect(wrapper.text()).toBe('No issues')
  })
})

describe('IssueList with a build mismatch', () => {
  const missing: ValidationIssue = {
    severity: 'error',
    code: 'encoder.unavailable',
    path: 'video.encoder',
    message: 'hevc_nvenc is not available: NVIDIA driver too old',
  }

  async function mountList(buildMismatch: boolean) {
    return mountShell(IssueList, {
      props: { issues: [missing] },
      setup: () => {
        useEditorStore().target = { job: { video: { encoder: 'hevc_nvenc' } } } as never
        useSystemStore().capabilities = {
          detecting: false,
          encoders: {
            hevc_nvenc: {
              id: 'hevc_nvenc',
              state: 'unavailable',
              hardware: true,
              build_mismatch: buildMismatch,
            },
          },
        } as never
      },
    })
  }

  it('offers another FFmpeg for the encoder issue, which opens Settings → Tools', async () => {
    const { wrapper, router } = await mountList(true)
    const other = wrapper.find('.rf-issue__other-ffmpeg')
    expect(other.text()).toBe('Use another FFmpeg…')
    await other.trigger('click')
    await vi.waitFor(() => expect(router.currentRoute.value.name).toBe('settings'))
    expect(router.currentRoute.value.hash).toBe('#tools')
    wrapper.unmount()
  })

  it('offers nothing more without a build mismatch', async () => {
    const { wrapper } = await mountList(false)
    expect(wrapper.find('.rf-issue__other-ffmpeg').exists()).toBe(false)
    wrapper.unmount()
  })
})
