/**
 * What the detached preview window shows, shared with the main window over a `BroadcastChannel`
 * (the two windows are pages of one origin). The main window's stores hold the truth: it sends
 * the editor's file and job, the tab, the view, the zoom and the frame. The preview window sends
 * back its user's choices and the edits of its crop handles, which the main window applies (its
 * history and validation see them); the main window then sends the job again.
 */
import { nextTick, onScopeDispose, type Ref, readonly, ref, watch } from 'vue'

import type { FrameLink, JobSettings, SourceEntry } from '@/api/types'
import type { EditorTabId } from '@/components/editor/tabs/registry'
import { isTextField } from '@/editor/focus'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore, type ViewMode, type Zoom } from '@/stores/preview'
import { useSourcesStore } from '@/stores/sources'
import { useUiStore } from '@/stores/ui'

export const PREVIEW_CHANNEL = 'reframe-preview-window'

interface Shown {
  sourceId: string
  job: JobSettings
  /** The sources store's entry: the probe the frames and the crop read. */
  entry: SourceEntry | null
}

interface Frame {
  index: number | null
  sought: FrameLink | null
}

/** Each field present has changed. */
interface Shared {
  shown?: Shown | null
  tab?: EditorTabId
  view?: ViewMode
  zoom?: Zoom
  frame?: Frame
}

/** The editor actions of the crop handles. */
const EDITS = ['set', 'patch', 'endCoalescing'] as const
type EditName = (typeof EDITS)[number]

type ToPreview = { kind: 'ask' } | { kind: 'state'; state: Shared }
type ToMain =
  | { kind: 'hello' }
  | { kind: 'bye' }
  | { kind: 'state'; state: Pick<Shared, 'view' | 'zoom' | 'frame'> }
  | { kind: 'edit'; name: EditName; args: unknown[] }

/**
 * The channel, closed with the caller's scope after `last` (if any) is sent. Messages go as
 * JSON: store values are reactive proxies, which a channel cannot clone.
 */
function channel<In, Out>(onMessage: (message: In) => void, last?: Out) {
  const bus = new BroadcastChannel(PREVIEW_CHANNEL)
  bus.addEventListener('message', (event: MessageEvent<string>) =>
    onMessage(JSON.parse(event.data) as In),
  )
  // oxlint-disable-next-line unicorn/require-post-message-target-origin -- a channel has no origin argument
  const post = (message: Out) => bus.postMessage(JSON.stringify(message))
  onScopeDispose(() => {
    if (last !== undefined) post(last)
    bus.close()
  })
  return post
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** The file and its job; the rest of an editor target or of a `Shown` does not count. */
function picture(value: { sourceId: string; job: JobSettings } | null) {
  return value === null ? null : { sourceId: value.sourceId, job: value.job }
}

function frameOf(preview: ReturnType<typeof usePreviewStore>): Frame {
  return { index: preview.index, sought: preview.sought }
}

function applyFrame(preview: ReturnType<typeof usePreviewStore>, frame: Frame): void {
  if (same(frameOf(preview), frame)) return
  preview.index = frame.index
  preview.sought = frame.sought
}

/**
 * The main window's side, for the scope of the preview panel. `detached` is true while a
 * preview window is open.
 */
export function shareWithPreviewWindow(): { detached: Readonly<Ref<boolean>> } {
  const editor = useEditorStore()
  const preview = usePreviewStore()
  const sources = useSourcesStore()
  const ui = useUiStore()
  const detached = ref(false)

  function shown(): Shown | null {
    const target = editor.target
    if (target === null) return null
    const entry = sources.entries.find((candidate) => candidate.id === target.sourceId) ?? null
    return { sourceId: target.sourceId, job: target.job, entry }
  }

  const post = channel<ToMain, ToPreview>((message) => {
    switch (message.kind) {
      case 'hello':
        detached.value = true
        send({
          shown: shown(),
          tab: ui.activeTab,
          view: preview.viewMode,
          zoom: preview.zoom,
          frame: frameOf(preview),
        })
        return
      case 'bye':
        detached.value = false
        return
      case 'state': {
        const { view, zoom, frame } = message.state
        if (view !== undefined) preview.viewMode = view
        if (zoom !== undefined) preview.zoom = zoom
        if (frame !== undefined) applyFrame(preview, frame)
        return
      }
      case 'edit':
        try {
          ;(editor[message.name] as (...args: unknown[]) => void)(...message.args)
        } catch (error) {
          // The preview window's job was older than this one: the next state corrects it.
          console.error('preview window edit failed', error)
        }
    }
  })

  function send(state: Shared): void {
    if (detached.value) post({ kind: 'state', state })
  }

  watch(shown, (value) => send({ shown: value }))
  watch(
    () => ui.activeTab,
    (tab) => send({ tab }),
  )
  watch(
    () => preview.viewMode,
    (view) => send({ view }),
  )
  watch(
    () => preview.zoom,
    (zoom) => send({ zoom }),
  )
  watch(
    () => frameOf(preview),
    (frame) => send({ frame }),
  )

  // A preview window opened before this page (re)loaded answers with its hello.
  post({ kind: 'ask' })
  return { detached: readonly(detached) }
}

/** The preview window's side: its stores follow the main window's, for the view's scope. */
export function followMainWindow(): void {
  const editor = useEditorStore()
  const preview = usePreviewStore()
  const sources = useSourcesStore()
  const ui = useUiStore()

  // In order: a new file resets the frame on the next tick, so its frame comes after that.
  let applying = Promise.resolve()

  async function apply(state: Shared): Promise<void> {
    const { shown } = state
    if (shown !== undefined && !same(picture(editor.target), picture(shown))) {
      const entry = shown?.entry
      if (entry) {
        sources.entries = [...sources.entries.filter((other) => other.id !== entry.id), entry]
      }
      editor.target =
        shown === null ? null : { kind: 'job', sourceId: shown.sourceId, job: shown.job }
      await nextTick()
    }
    if (state.tab !== undefined) ui.activeTab = state.tab
    if (state.view !== undefined) preview.viewMode = state.view
    if (state.zoom !== undefined) preview.zoom = state.zoom
    if (state.frame !== undefined) applyFrame(preview, state.frame)
  }

  const post = channel<ToPreview, ToMain>(
    (message) => {
      if (message.kind === 'ask') {
        post({ kind: 'hello' })
        return
      }
      applying = applying.then(() => apply(message.state))
    },
    { kind: 'bye' },
  )

  // What the main window sent comes back once; it changes nothing there.
  watch(
    () => preview.viewMode,
    (view) => post({ kind: 'state', state: { view } }),
  )
  watch(
    () => preview.zoom,
    (zoom) => post({ kind: 'state', state: { zoom } }),
  )
  // Only the user's frame choices: a new file's reset must not reach the main window.
  preview.$onAction(({ name, after }) => {
    if (name === 'select' || name === 'step' || name === 'seek') {
      after(() => post({ kind: 'state', state: { frame: frameOf(preview) } }))
    }
  })
  editor.$onAction(({ name, args }) => {
    if ((EDITS as readonly string[]).includes(name)) {
      post({ kind: 'edit', name: name as EditName, args })
    }
  })

  // A closed window ends its page without unmounting the view.
  const bye = () => post({ kind: 'bye' })
  addEventListener('pagehide', bye)
  onScopeDispose(() => removeEventListener('pagehide', bye))
  post({ kind: 'hello' })
}

/** A focused picture wider than its stage scrolls with the arrow keys. */
function scrollsSideways(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.dataset.field === 'stage' &&
    target.scrollWidth > target.clientWidth
  )
}

/** `←` / `→` step through the frames, except where the arrow keys already do something. */
export function stepOnArrowKeys(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
    return
  }
  const target = event.target
  if (isTextField(target) || scrollsSideways(target)) return
  if (
    target instanceof Element &&
    target.closest('[data-crop-handle], [role="slider"], input[type="range"]') !== null
  ) {
    return
  }
  event.preventDefault()
  usePreviewStore().step(event.key === 'ArrowRight' ? 1 : -1)
}
