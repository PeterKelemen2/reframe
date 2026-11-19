<script setup lang="ts">
import { ExternalLink, X } from '@lucide/vue'
import { until } from '@vueuse/core'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressBar from 'primevue/progressbar'
import SelectButton from 'primevue/selectbutton'
import { computed, nextTick, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { JobSettings, PreviewClip } from '@/api/types'
import { formatBytes } from '@/components/summary/format'
import { platform } from '@/platform'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'
import { TaskLostError, useTasksStore } from '@/stores/tasks'

import ClipCompare from './ClipCompare.vue'
import { absoluteUrl, CLIP_LENGTHS, reason } from './clip'

// `MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED`: the browser cannot decode the format.
const SRC_NOT_SUPPORTED = 4

const { t, n } = useI18n()
const editor = useEditorStore()
const crop = useCropStore()
const preview = usePreviewStore()
const tasks = useTasksStore()
const root = useTemplateRef<HTMLElement>('root')

/** A clip and what it was made from. */
interface Made {
  clip: PreviewClip
  sourceId: string
  /** The job as it was sent: a later edit makes the clip out of date. */
  job: JobSettings
}

const length = ref<number>(CLIP_LENGTHS[0])
const starting = ref(false)
const taskId = ref<string | null>(null)
const encodeError = ref<string | null>(null)
const cancelled = ref(false)
const made = shallowRef<Made | null>(null)
const link = ref<string | null>(null)
const linkError = ref<string | null>(null)
/** Why the player could not play the clip; the frame compare shows instead. */
const playError = ref<string | null>(null)
const comparing = ref(false)
/** `null` until the platform answers; a `<video>` is made only once it says `true`. */
const playable = ref<boolean | null>(null)
async function askPlayable(): Promise<void> {
  playable.value = await platform.canPlayVideo()
}
void askPlayable()
// Cancel came before the server named the task.
const stopAsked = ref(false)
// A clip link works for an hour: the first failure asks for a new one before giving up.
let linkRetried = false

const lengths = computed(() =>
  CLIP_LENGTHS.map((value) => ({ value, label: t('clip.seconds', { seconds: value }) })),
)
const running = computed(() => starting.value || taskId.value !== null)
const progress = computed(() => {
  const value = taskId.value === null ? null : tasks.tasks[taskId.value]?.progress
  return typeof value === 'number' ? value : null
})
const outOfDate = computed(
  () =>
    made.value !== null &&
    editor.job !== null &&
    JSON.stringify(editor.job) !== JSON.stringify(made.value.job),
)
// A detected crop enters the job when its detection ends: a clip sent before that keeps the bars.
const cropPending = computed(() => {
  const settings = editor.job?.dimensions?.crop
  return (
    (settings?.mode === 'auto' || settings?.mode === 'conservative') &&
    !settings.rect &&
    crop.detecting
  )
})

function time(seconds: number): string {
  return t('preview.seconds', { seconds: n(seconds, { maximumFractionDigits: 3 }) })
}

const summary = computed(() => {
  const clip = made.value?.clip
  if (clip === undefined) return null
  return t('clip.summary', {
    duration: time(clip.duration),
    start: time(clip.start),
    codec: clip.video_codec ?? clip.container,
    size: formatBytes(clip.size, t, n),
  })
})

async function encode(): Promise<void> {
  const frame = preview.current
  const sourceId = preview.sourceId
  if (editor.job === null || frame === null || sourceId === null) return
  encodeError.value = null
  cancelled.value = false
  stopAsked.value = false
  starting.value = true
  let id: string
  let job: JobSettings
  try {
    await until(() => !cropPending.value || stopAsked.value).toBe(true)
    if (stopAsked.value || editor.job === null) {
      cancelled.value = preview.sourceId === sourceId
      return
    }
    job = editor.job
    id = unwrap(
      await apiQuiet.POST('/api/preview/clip', {
        body: { job, start: frame.timestamp, seconds: length.value },
      }),
    ).task_id
  } catch (failure) {
    encodeError.value = reason(failure)
    return
  } finally {
    starting.value = false
  }
  if (stopAsked.value || preview.sourceId !== sourceId) {
    void stop(id)
    cancelled.value = preview.sourceId === sourceId
    return
  }
  taskId.value = id
  try {
    const task = await tasks.wait(id)
    if (taskId.value !== id) return
    if (task.state === 'done') {
      show({ clip: task.result as unknown as PreviewClip, sourceId, job })
    } else if (task.state === 'failed') {
      encodeError.value = task.error ?? t('clip.failedWithoutReason')
    } else {
      cancelled.value = true
    }
  } catch (failure) {
    if (!(failure instanceof TaskLostError)) throw failure
    if (taskId.value === id) encodeError.value = failure.message
  } finally {
    if (taskId.value === id) taskId.value = null
  }
}

async function cancel(): Promise<void> {
  if (taskId.value === null) stopAsked.value = true
  else await stop(taskId.value)
}

async function stop(id: string): Promise<void> {
  try {
    await tasks.cancel(id)
  } catch (error) {
    // The task ended first; the API client has shown the refusal as a toast.
    if (!(error instanceof ApiError)) throw error
  }
}

function show(next: Made): void {
  made.value = next
  link.value = null
  linkError.value = null
  playError.value = null
  comparing.value = false
  linkRetried = false
  void loadLink()
}

async function loadLink(): Promise<void> {
  const current = made.value
  if (current === null) return
  try {
    const answer = unwrap(
      await apiQuiet.GET('/api/preview/clips/{clip_id}/link', {
        params: { path: { clip_id: current.clip.id } },
      }),
    )
    if (made.value === current) link.value = absoluteUrl(answer.url)
  } catch (failure) {
    if (made.value === current) linkError.value = reason(failure)
  }
}

function played(): void {
  linkRetried = false
}

function playFailed(event: Event): void {
  if (!linkRetried) {
    linkRetried = true
    link.value = null
    void loadLink()
    return
  }
  const error = (event.target as HTMLVideoElement).error
  const clip = (made.value as Made).clip
  const codec = clip.video_codec ?? clip.container
  playError.value =
    error?.code === SRC_NOT_SUPPORTED
      ? t('clip.playback.unsupported', { codec })
      : t('clip.playback.failed', { reason: error?.message || String(error?.code ?? '') })
  comparing.value = true
}

function openExternal(): void {
  if (link.value !== null) void platform.openExternal(link.value)
}

watch([made, playable], ([clip, value]) => {
  if (clip === null || value !== false) return
  playError.value = t('clip.playback.noPlayer')
  comparing.value = true
})

// Another file drops the clip and stops an encode of the last one.
watch(
  () => preview.sourceId,
  (id) => {
    if (running.value) void cancel()
    taskId.value = null
    encodeError.value = null
    cancelled.value = false
    if (made.value?.sourceId !== id) made.value = null
  },
)

// The button under the focus is replaced while an encode runs.
watch(running, async (now) => {
  const active = document.activeElement
  if (active === null || root.value?.contains(active) !== true) return
  await nextTick()
  const next = now ? 'cancel-clip' : 'encode-clip'
  root.value?.querySelector<HTMLElement>(`[data-action="${next}"]`)?.focus()
})
</script>

<template>
  <section
    v-if="preview.sourceId !== null"
    ref="root"
    class="preview-clip"
    :aria-label="t('clip.title')"
  >
    <h3 class="preview-clip__title">{{ t('clip.title') }}</h3>
    <div class="preview-clip__controls">
      <SelectButton
        v-model="length"
        :options="lengths"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        size="small"
        :pt="{ root: { 'aria-label': t('clip.length') } }"
        data-field="clip-length"
      />
      <template v-if="running">
        <ProgressBar
          class="preview-clip__bar"
          :mode="progress === null ? 'indeterminate' : 'determinate'"
          :value="progress === null ? undefined : Math.round(progress)"
          :show-value="false"
          :pt="{ root: { 'aria-label': t('clip.encoding') } }"
          data-field="clip-progress"
        />
        <Button
          :label="t('clip.cancel')"
          severity="secondary"
          size="small"
          outlined
          data-action="cancel-clip"
          @click="cancel"
        >
          <template #icon><X :size="16" aria-hidden="true" /></template>
        </Button>
      </template>
      <Button
        v-else
        :label="t('clip.encode')"
        severity="secondary"
        size="small"
        :disabled="editor.job === null || preview.current === null"
        data-action="encode-clip"
        @click="encode"
      />
    </div>
    <p v-if="preview.current !== null && !running" class="preview-clip__hint">
      {{ t('clip.from', { start: time(preview.current.timestamp) }) }}
    </p>
    <p v-if="running" class="preview-clip__hint" data-field="clip-status" aria-live="polite">
      {{
        starting && cropPending
          ? t('clip.waitingForCrop')
          : progress === null
            ? t('clip.encoding')
            : t('clip.encodingPercent', { percent: Math.round(progress) })
      }}
    </p>
    <Message v-if="encodeError !== null" severity="error" :closable="false" data-field="clip-error">
      {{ t('clip.failed', { reason: encodeError }) }}
    </Message>
    <p v-if="cancelled" class="preview-clip__hint" data-field="clip-cancelled" aria-live="polite">
      {{ t('clip.cancelled') }}
    </p>

    <div v-if="made !== null" class="preview-clip__result" data-field="clip-result">
      <p class="preview-clip__summary" data-field="clip-summary">{{ summary }}</p>
      <Message v-if="outOfDate" severity="warn" :closable="false" data-field="clip-out-of-date">
        {{ t('clip.outOfDate') }}
      </Message>
      <Message v-if="linkError !== null" severity="error" :closable="false">
        {{ t('clip.linkFailed', { reason: linkError }) }}
      </Message>
      <Message
        v-if="playError !== null"
        severity="info"
        :closable="false"
        data-field="clip-play-error"
      >
        {{ t('clip.playback.fallback', { reason: playError }) }}
      </Message>
      <div class="preview-clip__actions">
        <Button
          v-if="playError === null"
          :label="comparing ? t('clip.play') : t('clip.compareFrames')"
          severity="secondary"
          size="small"
          outlined
          :data-action="comparing ? 'play-clip' : 'compare-frames'"
          @click="comparing = !comparing"
        />
        <Button
          :label="t('clip.openExternal')"
          severity="secondary"
          size="small"
          text
          :disabled="link === null"
          data-action="open-external"
          @click="openExternal"
        >
          <template #icon><ExternalLink :size="16" aria-hidden="true" /></template>
        </Button>
      </div>
      <ClipCompare v-if="comparing" :clip="made.clip" :source-id="made.sourceId" :job="made.job" />
      <video
        v-else-if="link !== null && playable === true"
        class="preview-clip__video"
        :src="link"
        :aria-label="t('clip.player')"
        controls
        preload="metadata"
        data-field="clip-video"
        @loadeddata="played"
        @error="playFailed"
      />
    </div>
  </section>
</template>

<style scoped>
.preview-clip {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-2);
  margin-top: var(--rf-space-4);
  padding-top: var(--rf-space-3);
  border-top: 1px solid var(--rf-color-border);
}

.preview-clip__title {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

.preview-clip__controls,
.preview-clip__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.preview-clip__bar {
  width: 6rem;
  height: 0.375rem;
}

.preview-clip__hint,
.preview-clip__summary {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.preview-clip__result {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-2);
}

.preview-clip__video {
  display: block;
  width: 100%;
  max-height: 60vh;
  background: #000;
}
</style>
