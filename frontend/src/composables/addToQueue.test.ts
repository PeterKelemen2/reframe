// The job that an add sends is the one the screen shows: real editor and validation stores, a
// PrimeVue InputNumber (it writes into the job only when it loses the focus), the naming editor
// and the Ctrl+Enter shortcut.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import InputNumber from 'primevue/inputnumber'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { configureClient } from '@/api/client'
import { FakeServer } from '@/api/testing/fakes'
import type { JobNaming, JobSettings, NameResult, QueueJob } from '@/api/types'
import JobNamingEditor from '@/components/naming/JobNamingEditor.vue'
import { hacksawResult, stubDom, VARIABLES } from '@/components/naming/testing/samples'
import { mountShell } from '@/components/shell/testing'
import { sampleDraft, sampleJob, samplePreset } from '@/editor/testing/samples'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

import { type QueueActions, useQueueActions } from './useQueueActions'
import { useShortcuts } from './useShortcuts'
import { useValidation } from './useValidation'

stubDom()

/** The server names the file from the template, with `{main_title}` as Hacksaw.Ridge. */
function named(job: JobSettings): NameResult {
  const given = job.output?.naming as JobNaming
  const stem =
    given.mode === 'manual'
      ? (given.manual_name ?? '')
      : (given.template ?? '{main_title}').replace('{main_title}', 'Hacksaw.Ridge')
  const relative = `${stem}.${job.output?.container ?? 'mkv'}`
  return hacksawResult({
    template: given.template ?? '{main_title}',
    relative_path: relative,
    path: `/output/${relative}`,
  })
}

function draftedJob(): JobSettings {
  const job = sampleJob()
  job.output!.path = '/output/Hacksaw.Ridge.mkv'
  return job
}

let server: FakeServer
let actions: QueueActions
const mounted: VueWrapper[] = []

/** The workspace's parts that matter here: the quality box, the naming editor, the shortcuts. */
const Workspace = defineComponent({
  setup() {
    useShortcuts()
    useValidation()
    actions = useQueueActions()
    const editor = useEditorStore()
    return () => [
      h(InputNumber, {
        inputId: 'quality',
        modelValue: (editor.job?.video?.rate_control as { value?: number } | undefined)?.value,
        minFractionDigits: 1,
        maxFractionDigits: 1,
        'onUpdate:modelValue': (value: number | null) => {
          if (typeof value === 'number') editor.set('/video/rate_control/value', value)
        },
      }),
      h(JobNamingEditor),
    ]
  },
})

function queued(): JobSettings[] {
  return server.requests
    .filter((request) => request.method === 'POST' && request.path === '/api/queue')
    .flatMap((request) => (request.body as { jobs: JobSettings[] }).jobs)
}

function ctrlEnter(target: Element): void {
  target.dispatchEvent(
    new KeyboardEvent('keydown', {
      key: 'Enter',
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    }),
  )
}

/** Lets the debounces, the fake server's answers and the add run to their end. */
async function settled(rounds = 5): Promise<void> {
  await vi.advanceTimersByTimeAsync(300)
  await flushPromises()
  if (rounds > 1) await settled(rounds - 1)
}

beforeEach(async () => {
  vi.useFakeTimers()
  server = new FakeServer()
    .on('POST /api/jobs/draft', () => ({ ...sampleDraft(draftedJob()), naming: hacksawResult() }))
    .on('POST /api/presets/diff', [])
    .on('GET /api/presets/h265-mkv-1080p', samplePreset())
    .on('POST /api/jobs/validate', [])
    .on('POST /api/naming/preview', (request) => [
      named((request.body as { job: JobSettings }).job),
    ])
    .on('POST /api/queue', (request) =>
      (request.body as { jobs: JobSettings[] }).jobs.map(
        (job, index): QueueJob =>
          ({
            id: `job-${index}`,
            position: index,
            state: 'waiting',
            settings: job,
            created_at: '2026-10-30T10:00:00Z',
          }) as QueueJob,
      ),
    )
  configureClient({ baseUrl: 'http://server', token: 't', fetch: server.fetch })
  const { wrapper } = await mountShell(Workspace, {
    setup: () => {
      useSystemStore().phase = 'ready'
      useSystemStore().namingVariables = VARIABLES
    },
  })
  mounted.push(wrapper)
  await useEditorStore().open('src')
  await settled()
})

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount()
  document.body.replaceChildren()
  vi.useRealTimers()
})

function qualityBox(): HTMLInputElement {
  return document.getElementById('quality') as HTMLInputElement
}

function templateField(): HTMLInputElement {
  return document.querySelector('.job-naming-editor input[role="combobox"]') as HTMLInputElement
}

describe('the job that is added', () => {
  it('has the quality typed into the focused box when Ctrl+Enter is pressed in it', async () => {
    const box = qualityBox()
    box.focus()
    // What typing leaves behind: the box shows the value, the job does not have it yet.
    box.value = '30'
    ctrlEnter(box)
    await settled()

    expect(queued().map((job) => job.video?.rate_control)).toEqual([{ mode: 'quality', value: 30 }])
    expect(document.activeElement).toBe(box)
  })

  it('has the template typed into the focused naming field, with its path, on Ctrl+Enter', async () => {
    const field = templateField()
    field.focus()
    field.value = '{main_title} MYNAME'
    field.dispatchEvent(new Event('input'))
    ctrlEnter(field)
    await settled()

    expect(queued().map((job) => [job.output?.naming?.template, job.output?.path])).toEqual([
      ['{main_title} MYNAME', '/output/Hacksaw.Ridge MYNAME.mkv'],
    ])
  })

  it('has a naming change made without typing when Add comes right after it', async () => {
    const field = templateField()
    field.value = '{main_title} CUSTOM'
    field.dispatchEvent(new Event('input'))
    field.dispatchEvent(new Event('blur'))
    await settled()
    expect(useEditorStore().job?.output?.naming?.template).toBe('{main_title} CUSTOM')

    const reset = document.querySelector('[data-action="reset-template"]') as HTMLButtonElement
    reset.click()
    expect(actions.canAdd.value).toBe(true)
    void actions.addCurrent()
    await settled()

    expect(queued().map((job) => [job.output?.naming?.template, job.output?.path])).toEqual([
      [null, '/output/Hacksaw.Ridge.mkv'],
    ])
  })

  it('keeps Add enabled when a click on it blurs the box that was typed in', async () => {
    const box = qualityBox()
    box.focus()
    box.value = '30'
    // The mousedown on the button takes the focus: the box writes its value into the job.
    box.blur()
    expect(useValidationStore().pending).toBe(true)
    expect(actions.canAdd.value).toBe(true)
    void actions.addCurrent()
    await settled()
    expect(queued().map((job) => job.video?.rate_control)).toEqual([{ mode: 'quality', value: 30 }])
  })
})
