<script setup lang="ts">
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import Button from 'primevue/button'
import Message from 'primevue/message'
import { computed, onScopeDispose, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet, unwrap } from '@/api/client'
import type { FrameLink, Geometry, JobSettings, PreviewClip } from '@/api/types'
import SplitCompare from '@/components/media/SplitCompare.vue'
import { type DecodedClip, useClipsStore } from '@/stores/clips'

import { absolute, compareTimes, millis, reason } from './clip'

const props = defineProps<{
  clip: PreviewClip
  /** The file the clip was made from. */
  sourceId: string
  /** The job the clip was made from: the source frames are cropped and turned as it says. */
  job: JobSettings
}>()

const { t, n } = useI18n()
const clips = useClipsStore()

interface Pair {
  /** Seconds from the start of the clip. */
  time: number
  before: FrameLink
  after: FrameLink
}

const pairs = shallowRef<Pair[]>([])
const geometry = shallowRef<Geometry | null>(null)
const at = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)
const notes = ref<string[]>([])
const broken = ref(false)
let request: AbortController | null = null
// A frame link expires after a few minutes: a failed image asks once again for every frame.
let retried = false

async function load(): Promise<void> {
  request?.abort()
  const own = new AbortController()
  request = own
  loading.value = true
  error.value = null
  const { id, start, duration } = props.clip
  const times = compareTimes(duration)
  try {
    const [clipFrames, sourceFrames, picture] = await Promise.all([
      apiQuiet
        .POST('/api/preview/clips/{clip_id}/frames', {
          params: { path: { clip_id: id } },
          body: { timestamps: times },
          signal: own.signal,
        })
        .then(unwrap),
      apiQuiet
        .POST('/api/preview/frames', {
          body: {
            source_id: props.sourceId,
            timestamps: times.map((offset) => millis(start + offset) / 1000),
          },
          signal: own.signal,
        })
        .then(unwrap),
      apiQuiet
        .POST('/api/jobs/geometry', { body: { job: props.job }, signal: own.signal })
        .then(unwrap),
    ])
    if (request !== own) return
    const sources = new Map(sourceFrames.frames.map((frame) => [millis(frame.timestamp), frame]))
    const decoded = {
      geometry: picture.geometry,
      pairs: clipFrames.frames.flatMap((after) => {
        const before = sources.get(millis(start + after.timestamp))
        return before === undefined
          ? []
          : [{ time: after.timestamp, before: absolute(before), after: absolute(after) }]
      }),
      notes: [...new Set([...clipFrames.notes, ...sourceFrames.notes])],
    }
    clips.keepDecoded(id, decoded)
    showDecoded(decoded)
  } catch (failure) {
    if (request !== own) return
    pairs.value = []
    error.value = reason(failure)
  } finally {
    if (request === own) {
      request = null
      loading.value = false
    }
  }
}

function showDecoded(decoded: DecodedClip): void {
  geometry.value = decoded.geometry
  pairs.value = decoded.pairs
  notes.value = decoded.notes
}

// A clip decoded before (a return from the player, or to its frame) shows at once.
watch(
  () => props.clip.id,
  (id) => {
    retried = false
    broken.value = false
    at.value = 0
    const decoded = clips.decodedClip(id)
    if (decoded === null) void load()
    else showDecoded(decoded)
  },
  { immediate: true },
)
onScopeDispose(() => request?.abort())

function failed(): void {
  if (retried) {
    broken.value = true
    return
  }
  retried = true
  void load()
}

// It goes round, so the focused button never becomes disabled under the focus.
function step(delta: 1 | -1): void {
  at.value = (at.value + delta + pairs.value.length) % pairs.value.length
}

const pair = computed(() => pairs.value[at.value] ?? null)

function time(seconds: number): string {
  return t('preview.seconds', { seconds: n(seconds, { maximumFractionDigits: 3 }) })
}
</script>

<template>
  <div class="clip-compare" data-field="clip-compare">
    <p v-if="loading && pair === null" class="clip-compare__state" aria-busy="true">
      {{ t('clip.compare.loading') }}
    </p>
    <div v-else-if="error !== null" class="clip-compare__state" data-state="compare-failed">
      <Message severity="error" :closable="false">
        {{ t('clip.compare.failed', { reason: error }) }}
      </Message>
      <Button
        :label="t('preview.retry')"
        severity="secondary"
        size="small"
        data-action="retry-compare"
        @click="load"
      />
    </div>
    <p v-else-if="broken" class="clip-compare__state" data-state="image-failed">
      {{ t('preview.imageFailed') }}
    </p>
    <p v-else-if="pair === null" class="clip-compare__state" data-state="no-frames">
      {{ t('clip.compare.none') }}
    </p>
    <template v-else>
      <SplitCompare
        :before="pair.before"
        :after="pair.after"
        :geometry="geometry"
        @failed="failed"
      />
      <div class="clip-compare__nav">
        <Button
          severity="secondary"
          text
          size="small"
          :aria-label="t('clip.compare.previous')"
          data-action="compare-previous"
          @click="step(-1)"
        >
          <template #icon><ChevronLeft :size="16" aria-hidden="true" /></template>
        </Button>
        <span class="clip-compare__position" data-field="compare-position" aria-live="polite">
          {{
            t('clip.compare.position', {
              n: at + 1,
              count: pairs.length,
              time: time(clip.start + pair.time),
            })
          }}
        </span>
        <Button
          severity="secondary"
          text
          size="small"
          :aria-label="t('clip.compare.next')"
          data-action="compare-next"
          @click="step(1)"
        >
          <template #icon><ChevronRight :size="16" aria-hidden="true" /></template>
        </Button>
      </div>
    </template>
    <ul v-if="notes.length > 0" class="clip-compare__notes" data-field="compare-notes">
      <li v-for="note in notes" :key="note">{{ note }}</li>
    </ul>
  </div>
</template>

<style scoped>
.clip-compare {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-2);
}

.clip-compare__state {
  display: grid;
  justify-items: start;
  gap: var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text-muted);
}

.clip-compare__nav {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.clip-compare__position {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.clip-compare__notes {
  margin: 0;
  padding-left: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
