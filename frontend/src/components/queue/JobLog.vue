<script setup lang="ts">
import { ArrowDownToLine, Copy } from '@lucide/vue'
import Button from 'primevue/button'
import Drawer from 'primevue/drawer'
import VirtualScroller from 'primevue/virtualscroller'
import { computed, nextTick, onMounted, ref, toRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import StatusDot from '@/components/base/StatusDot.vue'
import { useQueueStore } from '@/stores/queue'
import { useToastStore } from '@/stores/toasts'

import { sourceName, STATE_TONE, stateLabel } from './format'
import { useJobLog } from './useJobLog'

/** A job's whole log in a drawer, following the job while it writes. */
const props = defineProps<{ jobId: string | null }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const queue = useQueueStore()
const toasts = useToastStore()

const { lines, loading, failed, text } = useJobLog(toRef(props, 'jobId'))
const job = computed(() => (props.jobId === null ? undefined : queue.byId(props.jobId)))
const visible = computed(() => props.jobId !== null)

/** Stays at the end as lines arrive; scrolling up stops it, scrolling to the end starts it again. */
const following = ref(true)
const box = useTemplateRef<HTMLElement>('box')
/** A line's height in pixels: the virtual scroller needs one, and it follows the root font size. */
const lineHeight = ref(20)
const END_SLACK = 4

onMounted(() => {
  const root = Number.parseFloat(getComputedStyle(document.documentElement).fontSize)
  if (Number.isFinite(root) && root > 0) lineHeight.value = Math.round(root * 1.4)
})

function element(): HTMLElement | null {
  return box.value?.querySelector<HTMLElement>('.job-log__scroller') ?? null
}

function atEnd(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= END_SLACK
}

async function toEnd(): Promise<void> {
  await nextTick()
  // The scroller sizes its content for new items after its own update: wait for that frame.
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  const el = element()
  if (el !== null && following.value) el.scrollTop = el.scrollHeight
}

function onScroll(): void {
  const el = element()
  if (el !== null) following.value = atEnd(el)
}

function follow(): void {
  following.value = true
  void toEnd()
}

watch(
  () => props.jobId,
  () => {
    following.value = true
  },
)

// The drawer renders its content a moment after it opens, often after the first lines came.
watch(box, (el) => {
  if (el !== null && following.value) void toEnd()
})

watch(
  () => lines.value.length,
  () => {
    if (following.value) void toEnd()
  },
  { flush: 'post' },
)

async function copyAll(): Promise<void> {
  try {
    await navigator.clipboard.writeText(text())
    toasts.push({ severity: 'success', summary: t('queue.log.copied'), life: 3000 })
  } catch {
    toasts.push({ severity: 'error', summary: t('queue.log.copyFailed'), life: 6000 })
  }
}

function onVisible(value: boolean): void {
  if (!value) emit('close')
}
</script>

<template>
  <Drawer
    :visible="visible"
    position="right"
    class="job-log"
    :pt="{ root: { 'data-component': 'job-log', style: { width: 'min(64rem, 96vw)' } } }"
    @update:visible="onVisible"
  >
    <template #header>
      <div class="job-log__title">
        <h2 class="job-log__heading">
          {{ t('queue.log.title', { job: job ? sourceName(job) : '' }) }}
        </h2>
        <StatusDot
          v-if="job"
          :tone="STATE_TONE[job.state]"
          :label="stateLabel(job.state, t)"
          show-label
        />
      </div>
    </template>
    <div class="job-log__toolbar">
      <Button
        size="small"
        severity="secondary"
        :outlined="!following"
        :aria-pressed="following"
        data-action="follow"
        :label="t('queue.log.follow')"
        @click="following ? (following = false) : follow()"
      >
        <template #icon><ArrowDownToLine :size="16" aria-hidden="true" /></template>
      </Button>
      <Button
        size="small"
        severity="secondary"
        data-action="copy"
        :label="t('queue.log.copy')"
        :disabled="lines.length === 0"
        @click="copyAll"
      >
        <template #icon><Copy :size="16" aria-hidden="true" /></template>
      </Button>
      <span class="job-log__count" data-field="line-count">
        {{ t('queue.log.lines', lines.length) }}
      </span>
    </div>
    <p v-if="loading" class="job-log__note">{{ t('queue.log.loading') }}</p>
    <p v-else-if="failed" class="job-log__note" data-state="failed">
      {{ t('queue.log.failed') }}
    </p>
    <p v-else-if="lines.length === 0" class="job-log__note" data-state="empty">
      {{ t('queue.log.empty') }}
    </p>
    <div v-if="lines.length > 0" ref="box" role="log" :aria-label="t('queue.log.label')">
      <VirtualScroller
        class="job-log__scroller"
        :items="lines as string[]"
        :item-size="lineHeight"
        tabindex="0"
        @scroll="onScroll"
      >
        <template #item="{ item }">
          <div
            class="job-log__line"
            :style="{ height: `${lineHeight}px`, lineHeight: `${lineHeight}px` }"
          >
            {{ item }}
          </div>
        </template>
      </VirtualScroller>
    </div>
  </Drawer>
</template>

<style scoped>
.job-log__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
  min-width: 0;
}

.job-log__heading {
  margin: 0;
  overflow-wrap: anywhere;
  font-size: var(--rf-font-size-lg);
}

.job-log__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  margin-bottom: var(--rf-space-3);
}

.job-log__count,
.job-log__note {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.job-log__scroller {
  height: calc(100vh - 10rem);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-bg);
}

/* PrimeVue's scroller removes the outline that the app's focus ring is. */
.job-log__scroller:focus-visible {
  outline: var(--p-focus-ring-width) var(--p-focus-ring-style) var(--p-focus-ring-color);
  outline-offset: var(--p-focus-ring-offset);
}

.job-log__line {
  padding-inline: var(--rf-space-2);
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  white-space: pre;
}
</style>
