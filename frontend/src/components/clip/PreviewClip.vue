<script setup lang="ts">
import { ExternalLink, X } from '@lucide/vue'
import Button from 'primevue/button'
import Message from 'primevue/message'
import ProgressBar from 'primevue/progressbar'
import SelectButton from 'primevue/selectbutton'
import { computed, nextTick, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet, unwrap } from '@/api/client'
import { formatBytes } from '@/components/summary/format'
import { platform } from '@/platform'
import { type MadeClip, useClipsStore } from '@/stores/clips'
import { useEditorStore } from '@/stores/editor'
import { usePreviewStore } from '@/stores/preview'

import ClipCompare from './ClipCompare.vue'
import { absoluteUrl, CLIP_LENGTHS, reason } from './clip'

// `MediaError.MEDIA_ERR_DECODE`: the decoder failed, which a new link cannot fix.
const DECODE = 3
// `MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED`: the browser cannot decode the format.
const SRC_NOT_SUPPORTED = 4

const { t, n } = useI18n()
const editor = useEditorStore()
const preview = usePreviewStore()
const clips = useClipsStore()
const root = useTemplateRef<HTMLElement>('root')

/** The clip of the shown frame, length and job. */
const made = computed(() => clips.shown)
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
// A clip link works for an hour: the first failure asks for a new one before giving up.
let linkRetried = false

const lengths = computed(() =>
  CLIP_LENGTHS.map((value) => ({ value, label: t('clip.seconds', { seconds: value }) })),
)

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

// Another clip is shown (another frame, length or job): its own link, player and compare.
watch(
  made,
  (next, previous) => {
    if (next === previous) return
    link.value = null
    linkError.value = null
    playError.value = null
    comparing.value = false
    linkRetried = false
    if (next !== null) void loadLink()
  },
  { immediate: true },
)

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

function played(event: Event): void {
  linkRetried = false
  // A webview without the codec's decoder can still play the audio of a clip and report
  // no error; a picture without width is the only sign.
  if ((event.target as HTMLVideoElement).videoWidth === 0) unplayable()
}

function unplayable(): void {
  const clip = (made.value as MadeClip).clip
  playError.value = t('clip.playback.unsupported', { codec: clip.video_codec ?? clip.container })
  comparing.value = true
}

function playFailed(event: Event): void {
  const error = (event.target as HTMLVideoElement).error
  // A webview without a working decoder for the codec can fail after it showed a picture.
  if (error?.code === DECODE) {
    unplayable()
    return
  }
  if (!linkRetried) {
    linkRetried = true
    link.value = null
    void loadLink()
    return
  }
  if (error?.code === SRC_NOT_SUPPORTED) {
    unplayable()
    return
  }
  playError.value = t('clip.playback.failed', {
    reason: error?.message || String(error?.code ?? ''),
  })
  comparing.value = true
}

/** The desktop app hands the clip to the system's player; a browser opens it in a new tab. */
const inBrowser = platform.desktop === null
const fallbackKey = inBrowser ? 'clip.playback.fallbackTab' : 'clip.playback.fallback'

function openExternal(): void {
  if (link.value !== null) void platform.openExternal(link.value)
}

watch([made, playable], ([clip, value]) => {
  if (clip === null || value !== false) return
  playError.value = t('clip.playback.noPlayer')
  comparing.value = true
})

// The button under the focus is replaced while an encode runs.
watch(
  () => clips.running,
  async (now) => {
    const active = document.activeElement
    if (active === null || root.value?.contains(active) !== true) return
    await nextTick()
    const next = now ? 'cancel-clip' : 'encode-clip'
    root.value?.querySelector<HTMLElement>(`[data-action="${next}"]`)?.focus()
  },
)
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
        v-model="clips.length"
        :options="lengths"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        size="small"
        :pt="{ root: { 'aria-label': t('clip.length') } }"
        data-field="clip-length"
      />
      <template v-if="clips.running">
        <ProgressBar
          class="preview-clip__bar"
          :mode="clips.progress === null ? 'indeterminate' : 'determinate'"
          :value="clips.progress === null ? undefined : Math.round(clips.progress)"
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
          @click="clips.cancel"
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
        @click="clips.encode"
      />
    </div>
    <p v-if="preview.current !== null && !clips.running" class="preview-clip__hint">
      {{ t('clip.from', { start: time(preview.current.timestamp) }) }}
    </p>
    <p v-if="clips.running" class="preview-clip__hint" data-field="clip-status" aria-live="polite">
      {{
        clips.starting && clips.cropPending
          ? t('clip.waitingForCrop')
          : clips.progress === null
            ? t('clip.encoding')
            : t('clip.encodingPercent', { percent: Math.round(clips.progress) })
      }}
    </p>
    <Message
      v-if="clips.encodeError !== null"
      severity="error"
      :closable="false"
      data-field="clip-error"
    >
      {{ t('clip.failed', { reason: clips.encodeError }) }}
    </Message>
    <p
      v-if="clips.cancelled"
      class="preview-clip__hint"
      data-field="clip-cancelled"
      aria-live="polite"
    >
      {{ t('clip.cancelled') }}
    </p>

    <p v-if="clips.othersOnly" class="preview-clip__hint" data-field="clip-none">
      {{ t('clip.noneForThis') }}
    </p>

    <div v-if="made !== null" class="preview-clip__result" data-field="clip-result">
      <p class="preview-clip__summary" data-field="clip-summary">{{ summary }}</p>
      <Message v-if="linkError !== null" severity="error" :closable="false">
        {{ t('clip.linkFailed', { reason: linkError }) }}
      </Message>
      <Message
        v-if="playError !== null"
        severity="info"
        :closable="false"
        data-field="clip-play-error"
      >
        {{ t(fallbackKey, { reason: playError }) }}
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
          :label="inBrowser ? t('clip.openTab') : t('clip.openExternal')"
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

/* The same joined segments as the frame viewer's: the preview column has one control style. */
.preview-clip__controls :deep(.p-selectbutton) {
  --p-selectbutton-border-radius: var(--rf-radius-md);
  --p-togglebutton-sm-padding: 0;
  --p-togglebutton-content-sm-padding: 0.25rem 0.75rem;
  --p-togglebutton-background: transparent;
  --p-togglebutton-border-color: var(--p-form-field-border-color);
  --p-togglebutton-color: var(--rf-color-text);
  --p-togglebutton-hover-background: var(--rf-color-surface-hover);
  --p-togglebutton-hover-color: var(--rf-color-text);
  --p-togglebutton-checked-background: var(--rf-color-primary);
  --p-togglebutton-checked-border-color: var(--rf-color-primary);
  --p-togglebutton-checked-color: var(--rf-color-on-primary);
  --p-togglebutton-content-checked-background: transparent;
  --p-togglebutton-content-checked-shadow: none;

  background: transparent;
}

.preview-clip__controls :deep(.p-togglebutton) {
  font-weight: var(--rf-font-weight-medium);
}
</style>
