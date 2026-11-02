<script setup lang="ts">
import { TriangleAlert } from '@lucide/vue'
import Dialog from 'primevue/dialog'
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FrameLink } from '@/api/types'
import { formatTime } from '@/components/chapters/chapters'
import { type PictureSize, useCropStore } from '@/stores/crop'
import { usePreviewStore } from '@/stores/preview'

import { type Box, type CheckAnswer, type CheckRequest, removedBands } from './cropCheck'
import { fetchFrame } from './frames'
import { NO_CROP } from './magnifier'

/** *Check crop on all frames*: every sample frame with the crop and its detected black bars. */
const visible = defineModel<boolean>('visible', { required: true })

const { t } = useI18n()
const preview = usePreviewStore()
const crop = useCropStore()

/** Object URLs of the fetched PNGs, by frame key: the worker reads the same bytes. */
const images = shallowRef(new Map<string, string>())
const answers = shallowRef(new Map<string, CheckAnswer>())
const failed = ref(false)
let worker: Worker | null = null
let run = 0

function stop(): void {
  run += 1
  worker?.terminate()
  worker = null
  for (const url of images.value.values()) URL.revokeObjectURL(url)
  images.value = new Map()
  answers.value = new Map()
  failed.value = false
}

async function check(links: FrameLink[], size: PictureSize): Promise<void> {
  stop()
  const own = run
  const bands = removedBands(crop.rect ?? NO_CROP, size)
  let blobs: Blob[]
  try {
    blobs = await Promise.all(links.map(fetchFrame))
  } catch {
    // The links expire after a few minutes; a new strip runs the check again.
    if (own === run && !preview.imageFailed(links[0]!)) failed.value = true
    return
  }
  if (own !== run) return
  images.value = new Map(links.map((link, i) => [link.key, URL.createObjectURL(blobs[i]!)]))
  const started = new Worker(new URL('./cropCheck.worker.ts', import.meta.url), {
    type: 'module',
  })
  started.addEventListener('message', (event: MessageEvent<CheckAnswer>) => {
    if (worker !== started) return
    answers.value = new Map(answers.value).set(event.data.key, event.data)
  })
  worker = started
  links.forEach((link, i) => {
    const request: CheckRequest = { key: link.key, blob: blobs[i]!, bands }
    // oxlint-disable-next-line unicorn/require-post-message-target-origin -- a worker has no origin to name
    started.postMessage(request)
  })
}

watch(
  () => [visible.value, preview.strip, crop.rect, crop.sourceSize] as const,
  ([shown, links, , size]) => {
    if (shown && size !== null) {
      void check(links, size)
      return
    }
    stop()
  },
  { immediate: true },
)
onBeforeUnmount(stop)

function percent(box: Box, size: PictureSize): Record<string, string> {
  return {
    left: `${(box.x / size.width) * 100}%`,
    top: `${(box.y / size.height) * 100}%`,
    width: `${(box.width / size.width) * 100}%`,
    height: `${(box.height / size.height) * 100}%`,
  }
}

const items = computed(() => {
  const size = crop.sourceSize
  if (size === null) return []
  const rect = crop.rect ?? NO_CROP
  const kept = percent(
    {
      x: rect.left,
      y: rect.top,
      width: size.width - rect.left - rect.right,
      height: size.height - rect.top - rect.bottom,
    },
    size,
  )
  return preview.strip.map((link, index) => {
    const bars = crop.detection?.samples.find((sample) => sample.timestamp === link.timestamp)?.crop
    return {
      link,
      index,
      time: formatTime(link.timestamp),
      image: images.value.get(link.key) ?? null,
      answer: answers.value.get(link.key) ?? null,
      bars: bars ?? null,
      barBoxes: bars ? removedBands(bars, size).map((band) => percent(band, size)) : [],
      kept,
    }
  })
})

const lostCount = computed(() => items.value.filter((item) => item.answer?.lost).length)
const done = computed(
  () => items.value.length > 0 && items.value.every((item) => item.answer !== null),
)

function show(index: number): void {
  preview.select(index)
  visible.value = false
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    class="crop-check"
    :header="t('crop.check.title')"
    :style="{ width: 'min(64rem, calc(100vw - 2rem))' }"
    data-dialog="crop-check"
  >
    <p class="crop-check__intro">{{ t('crop.check.intro') }}</p>
    <p v-if="failed" class="crop-check__state" role="alert">{{ t('crop.check.failed') }}</p>
    <p v-else class="crop-check__state" aria-live="polite" data-check-summary>
      {{
        done
          ? t('crop.check.summary', { n: lostCount, count: items.length }, lostCount)
          : t('crop.check.checking')
      }}
    </p>
    <ul class="crop-check__frames">
      <li v-for="item in items" :key="item.link.key">
        <button
          type="button"
          class="crop-check__frame"
          :aria-label="t('crop.check.show', { time: item.time })"
          :data-frame="item.index"
          :data-lost="item.answer === null ? undefined : String(item.answer.lost)"
          @click="show(item.index)"
        >
          <span
            class="crop-check__picture"
            :style="{ aspectRatio: `${item.link.width} / ${item.link.height}` }"
          >
            <img v-if="item.image !== null" class="crop-check__image" :src="item.image" alt="" />
            <span
              v-for="(bar, i) in item.barBoxes"
              :key="i"
              class="crop-check__bar"
              :style="bar"
              data-bar
            />
            <span class="crop-check__kept" :style="item.kept" />
          </span>
          <span class="crop-check__caption">
            <span>{{ item.time }}</span>
            <span class="crop-check__bars">
              {{
                item.bars !== null
                  ? t('crop.check.bars', item.bars)
                  : crop.detecting
                    ? t('crop.check.detecting')
                    : t('crop.check.noResult')
              }}
            </span>
          </span>
          <span v-if="item.answer?.lost" class="crop-check__badge" data-badge="lost">
            <TriangleAlert :size="14" aria-hidden="true" />
            {{ t('crop.check.lost') }}
          </span>
        </button>
      </li>
    </ul>
  </Dialog>
</template>

<style scoped>
.crop-check__intro,
.crop-check__state {
  margin: 0 0 var(--rf-space-3);
}

.crop-check__intro {
  color: var(--rf-color-text-muted);
}

.crop-check__frames {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
  gap: var(--rf-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.crop-check__frame {
  display: grid;
  gap: var(--rf-space-1);
  width: 100%;
  padding: var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
  color: var(--rf-color-text);
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.crop-check__frame:hover {
  background: var(--rf-color-surface-hover);
}

.crop-check__frame:focus-visible {
  outline: 2px solid var(--p-focus-ring-color);
  outline-offset: 2px;
}

.crop-check__picture {
  position: relative;
  display: block;
  overflow: hidden;
  background: #000;
}

.crop-check__image {
  display: block;
  width: 100%;
  height: 100%;
}

.crop-check__bar,
.crop-check__kept {
  position: absolute;
}

/* Hatched, so that the detected bars read apart from the tint of the crop. */
.crop-check__bar {
  background: repeating-linear-gradient(45deg, rgb(0 200 255 / 0.7) 0 2px, transparent 2px 6px);
}

/* The removed area is everything outside the kept rectangle. */
.crop-check__kept {
  outline: 2px solid #ffd400;
  box-shadow: 0 0 0 100vmax rgb(255 0 90 / 0.35);
}

.crop-check__caption {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--rf-space-1) var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
  font-variant-numeric: tabular-nums;
}

.crop-check__bars {
  color: var(--rf-color-text-muted);
}

.crop-check__badge {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: var(--rf-space-1);
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-pill);
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
  font-size: var(--rf-font-size-sm);
}
</style>
