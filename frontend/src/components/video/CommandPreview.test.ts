import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { settle } from '@/api/testing/fakes'
import { mountShell } from '@/components/shell/testing'

import CommandPreview from './CommandPreview.vue'
import { openJob, setUpVideo } from './testing'

const DISPLAY =
  'ffmpeg -i /m/a.mkv -filter:v:0 scale=1280:720 -c:v:0 libx265 /o/a.part.mkv && mv -f -- /o/a.part.mkv /o/a.mkv'

const mounted: { unmount(): void }[] = []

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  localStorage.clear()
})

async function mountPreview(answer: unknown = { display: DISPLAY, steps: [] }) {
  const setup = setUpVideo()
  setup.server.on('POST /api/jobs/plan', answer)
  await openJob()
  const { wrapper } = await mountShell(CommandPreview, { pinia: setup.pinia })
  mounted.push(wrapper)
  await wrapper.find('.command-preview__toggle').trigger('click')
  await settle()
  await flushPromises()
  return { ...setup, wrapper }
}

describe('the command preview', () => {
  it('asks for nothing until it is opened', async () => {
    const setup = setUpVideo()
    await openJob()
    const { wrapper } = await mountShell(CommandPreview, { pinia: setup.pinia })
    mounted.push(wrapper)
    await settle()
    expect(setup.server.count('POST /api/jobs/plan')).toBe(0)
    expect(wrapper.find('.command-preview__toggle').attributes('aria-expanded')).toBe('false')
  })

  it('shows the command one step per line, coloured by kind', async () => {
    const { wrapper } = await mountPreview()
    const lines = wrapper.findAll('.command-preview__line').map((line) => line.text())
    expect(lines).toEqual([
      'ffmpeg -i /m/a.mkv -filter:v:0 scale=1280:720 -c:v:0 libx265 /o/a.part.mkv &&',
      'mv -f -- /o/a.part.mkv /o/a.mkv',
    ])
    const kind = (text: string) =>
      wrapper
        .findAll('.command-preview__code span span')
        .find((span) => span.text() === text)
        ?.classes()
    expect(kind('-filter:v:0')).toContain('cmd-option')
    expect(kind('scale=1280:720')).toContain('cmd-filter')
    expect(kind('/m/a.mkv')).toContain('cmd-path')
    expect(kind('libx265')).toContain('cmd-value')
  })

  it('copies the command exactly as the server wrote it', async () => {
    // jsdom has no clipboard permission, so the copy takes the legacy path (a text area).
    let copied: string | undefined
    document.execCommand = vi.fn<(command: string) => boolean>(() => {
      copied = document.querySelector('textarea')?.value
      return true
    })
    const { wrapper } = await mountPreview()
    await wrapper.find('.command-preview__copy').trigger('click')
    await flushPromises()
    expect(copied).toBe(DISPLAY)
    expect(wrapper.find('.command-preview__copy').text()).toBe('Copied')
  })

  it("lists the job's errors instead of a command", async () => {
    const issues = [
      {
        severity: 'error',
        code: 'encoder.unavailable',
        path: 'video.encoder',
        message: 'No NVENC',
      },
    ]
    const answer = new Response(
      JSON.stringify({
        type: 'about:blank',
        title: 'The job has errors',
        status: 422,
        code: 'jobs.invalid',
        issues,
      }),
      { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
    )
    const { wrapper } = await mountPreview(() => answer.clone())
    expect(wrapper.find('.command-preview__code').exists()).toBe(false)
    expect(wrapper.find('.command-preview__problem').text()).toContain(
      'There is no command while the job has errors',
    )
    expect(wrapper.find('.rf-issue').text()).toContain('No NVENC')
  })
})
