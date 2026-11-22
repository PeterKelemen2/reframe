<script setup lang="ts">
import { CircleX } from '@lucide/vue'
import Button from 'primevue/button'
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { Fix } from '@/api/types'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useValidationStore } from '@/stores/validation'

/**
 * Shown while the job's encoder is unavailable (`encoder.unavailable`): the reason, the issue's
 * fixes, *Choose encoder*, *Use another FFmpeg…* when another build can help, and *Check
 * again*. It never blocks the tab.
 */
const emit = defineEmits<{ choose: [] }>()

const { t } = useI18n()
const router = useRouter()
const editor = useEditorStore()
const system = useSystemStore()
const validation = useValidationStore()
const headingId = useId()

const issue = computed(
  () =>
    validation.issuesFor('video.encoder').find((found) => found.code === 'encoder.unavailable') ??
    null,
)
const encoder = computed(() => editor.job?.video?.encoder ?? '')
const reason = computed(() => system.encoderStatus(encoder.value)?.reason ?? null)
const buildMismatch = computed(() => system.encoderStatus(encoder.value)?.build_mismatch === true)
/** The preset's name while the job still has the preset's encoder; after a change it is the job's. */
const presetName = computed(() => {
  const preset = editor.preset
  return preset !== null && preset.video?.encoder === encoder.value ? preset.name : null
})
const fixes = computed(() => (issue.value?.fixes ?? []).filter((fix) => fix.target !== 'template'))

const applying = ref<Fix | null>(null)
const checking = ref(false)

async function apply(fix: Fix): Promise<void> {
  if (applying.value !== null) return
  applying.value = fix
  try {
    await editor.applyFix(fix)
  } finally {
    applying.value = null
  }
}

async function otherFfmpeg(): Promise<void> {
  await router.push({ name: 'settings', hash: '#tools' })
}

async function checkAgain(): Promise<void> {
  checking.value = true
  try {
    await system.rescanEncoders()
  } catch (error) {
    // The API client has shown the problem as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    checking.value = false
  }
}
</script>

<template>
  <section v-if="issue" class="encoder-banner" role="alert" :aria-labelledby="headingId">
    <CircleX class="encoder-banner__icon" :size="20" aria-hidden="true" />
    <div class="encoder-banner__body">
      <h3 :id="headingId" class="encoder-banner__title">{{ t('video.banner.title') }}</h3>
      <i18n-t
        v-if="reason !== null && presetName !== null"
        keypath="video.banner.preset"
        tag="p"
        class="encoder-banner__message"
      >
        <template #preset>
          <em>{{ presetName }}</em>
        </template>
        <template #encoder>
          <code>{{ encoder }}</code>
        </template>
        <template #reason>{{ reason }}</template>
      </i18n-t>
      <i18n-t
        v-else-if="reason !== null"
        keypath="video.banner.job"
        tag="p"
        class="encoder-banner__message"
      >
        <template #encoder>
          <code>{{ encoder }}</code>
        </template>
        <template #reason>{{ reason }}</template>
      </i18n-t>
      <p v-else class="encoder-banner__message">{{ issue.message }}</p>
      <div class="encoder-banner__actions">
        <Button
          v-for="fix in fixes"
          :key="fix.label"
          class="encoder-banner__fix"
          size="small"
          :label="fix.label"
          :loading="applying === fix"
          :disabled="applying !== null"
          @click="apply(fix)"
        />
        <Button
          class="encoder-banner__choose"
          size="small"
          severity="secondary"
          outlined
          :label="t('video.banner.choose')"
          @click="emit('choose')"
        />
        <Button
          v-if="buildMismatch"
          class="encoder-banner__other-ffmpeg"
          size="small"
          severity="secondary"
          outlined
          :label="t('video.banner.otherFfmpeg')"
          @click="otherFfmpeg"
        />
        <Button
          class="encoder-banner__check"
          size="small"
          severity="secondary"
          outlined
          :label="t('video.banner.checkAgain')"
          :loading="checking"
          :disabled="checking"
          @click="checkAgain"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.encoder-banner {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--rf-space-3);
  padding: var(--rf-space-3) var(--rf-space-4);
  border: 1px solid var(--p-status-error-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-error-background);
  color: var(--rf-color-text);
}

.encoder-banner__icon {
  margin-top: 0.1em;
  color: var(--p-status-error-color);
}

.encoder-banner__body {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.encoder-banner__title {
  margin: 0;
  color: var(--p-status-error-color);
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
}

.encoder-banner__message {
  margin: 0;
  overflow-wrap: anywhere;
}

.encoder-banner__message code {
  font-family: var(--rf-font-mono);
}

.encoder-banner__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}
</style>
