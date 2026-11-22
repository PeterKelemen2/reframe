<script setup lang="ts">
import Button from 'primevue/button'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { Fix, QueueJob, ValidationIssue } from '@/api/types'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'

import { sourceName } from './format'

/**
 * The fix actions of a job that failed because its encoder was not available, as the Video
 * tab's banner offers them: a fix replaces the job with its fixed settings, *Choose encoder*
 * opens the job in the workspace at its encoder, and *Check again* detects the encoders again
 * and retries the job when its encoder is available now.
 */
const props = defineProps<{ job: QueueJob; issue: ValidationIssue }>()
const emit = defineEmits<{ choose: [path: string] }>()

const { t } = useI18n()
const router = useRouter()
const queue = useQueueStore()
const system = useSystemStore()

const fixes = computed(() => (props.issue.fixes ?? []).filter((fix) => fix.target !== 'template'))
const path = computed(() => props.issue.path || 'video.encoder')

/** The encoder at the issue's path: `video.encoder` or `audio[i].encoder`. */
const encoder = computed(() => {
  const settings = props.job.settings
  const audio = /^audio\[(\d+)\]\.encoder$/.exec(path.value)
  if (audio) return settings.audio?.[Number(audio[1])]?.encoder ?? ''
  return settings.video?.encoder ?? ''
})
const buildMismatch = computed(() => system.encoderStatus(encoder.value)?.build_mismatch === true)

const busy = ref<Fix | 'check' | null>(null)

async function run(what: Fix | 'check', action: () => Promise<void>): Promise<void> {
  if (busy.value !== null) return
  busy.value = what
  try {
    await action()
  } catch (error) {
    // The API client has shown the problem as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    busy.value = null
  }
}

function apply(fix: Fix): void {
  void run(fix, () => queue.retryWith(props.job.id, fix))
}

function checkAgain(): void {
  void run('check', async () => {
    await system.rescanEncoders()
    if (system.encoderStatus(encoder.value)?.state === 'available') await queue.retry(props.job.id)
  })
}

async function otherFfmpeg(): Promise<void> {
  await router.push({ name: 'settings', hash: '#tools' })
}
</script>

<template>
  <div
    class="encoder-fixes"
    role="group"
    :aria-label="t('queue.encoderFixes', { job: sourceName(job) })"
    data-field="encoder-fixes"
  >
    <Button
      v-for="fix in fixes"
      :key="fix.label"
      class="encoder-fixes__fix"
      size="small"
      :label="fix.label"
      :loading="busy === fix"
      :disabled="busy !== null"
      @click="apply(fix)"
    />
    <Button
      class="encoder-fixes__choose"
      size="small"
      severity="secondary"
      outlined
      :label="t('video.banner.choose')"
      :disabled="busy !== null"
      @click="emit('choose', path)"
    />
    <Button
      v-if="buildMismatch"
      class="encoder-fixes__other-ffmpeg"
      size="small"
      severity="secondary"
      outlined
      :label="t('video.banner.otherFfmpeg')"
      @click="otherFfmpeg"
    />
    <Button
      class="encoder-fixes__check"
      size="small"
      severity="secondary"
      outlined
      :label="t('video.banner.checkAgain')"
      :loading="busy === 'check'"
      :disabled="busy !== null"
      @click="checkAgain"
    />
  </div>
</template>

<style scoped>
.encoder-fixes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}
</style>
