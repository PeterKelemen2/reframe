<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { pipelineOf } from '@/components/summary/pipeline'
import { useCropStore } from '@/stores/crop'
import { useValidationStore } from '@/stores/validation'

import { headerOf } from './header'

const { t } = useI18n()
const crop = useCropStore()
const validation = useValidationStore()

const line = computed(() => (crop.geometry === null ? null : headerOf(crop.geometry, t)))
const pipeline = computed(() => (crop.geometry === null ? null : pipelineOf(crop.geometry)))
const invalid = computed(
  () =>
    crop.geometryError !== null ||
    validation
      .issuesFor('dimensions', { nested: true })
      .some((issue) => issue.severity === 'error'),
)
const upscaled = computed(() => pipeline.value?.kind === 'encoded' && pipeline.value.upscaled)
const tone = computed(() => (invalid.value ? 'error' : upscaled.value ? 'warn' : null))
const notes = computed(() => (pipeline.value?.kind === 'encoded' ? pipeline.value.notes : []))
</script>

<template>
  <div class="pipeline-header" data-field="pipeline">
    <p
      class="pipeline-header__line"
      :class="tone && `pipeline-header__line--${tone}`"
      :aria-label="t('dimensions.header.label')"
      :aria-busy="crop.geometryPending"
      :data-tone="tone ?? undefined"
      role="status"
    >
      <template v-if="crop.geometryError !== null">
        {{ t('dimensions.header.failed', { reason: crop.geometryError }) }}
      </template>
      <template v-else>{{ line ?? t('dimensions.header.computing') }}</template>
    </p>
    <p v-if="tone === 'error' && crop.geometryError === null" class="pipeline-header__tone">
      {{ t('dimensions.header.invalid') }}
    </p>
    <p v-else-if="tone === 'warn'" class="pipeline-header__tone">
      {{ t('dimensions.header.upscaled') }}
    </p>
    <ul v-if="notes.length > 0" class="pipeline-header__notes">
      <li v-for="note in notes" :key="note">{{ note }}</li>
    </ul>
  </div>
</template>

<style scoped>
.pipeline-header {
  display: grid;
  gap: var(--rf-space-1);
}

.pipeline-header__line {
  margin: 0;
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-medium);
  overflow-wrap: anywhere;
}

.pipeline-header__line--warn,
.pipeline-header__line--warn + .pipeline-header__tone {
  color: var(--p-status-warn-color);
}

.pipeline-header__line--error,
.pipeline-header__line--error + .pipeline-header__tone {
  color: var(--p-status-error-color);
}

.pipeline-header__tone {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

.pipeline-header__notes {
  margin: 0;
  padding-left: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
