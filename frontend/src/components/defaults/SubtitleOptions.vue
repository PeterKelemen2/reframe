<script setup lang="ts">
import Checkbox from 'primevue/checkbox'
import Select from 'primevue/select'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SubtitleDefaults } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useDefaultsStore } from '@/stores/defaults'

import IssueLines from './IssueLines.vue'
import { useDefaultsOptions } from './options'

/** Foreign audio search and burn-in, the subtitle defaults' own settings. */
const { t } = useI18n()
const defaults = useDefaultsStore()
const choices = useDefaultsOptions()
const id = useId()

const value = computed(() => defaults.subtitles as SubtitleDefaults)

function set(next: Partial<SubtitleDefaults>): void {
  if (defaults.subtitles !== null) defaults.setSubtitles({ ...defaults.subtitles, ...next })
}
</script>

<template>
  <div class="subtitle-options">
    <div class="subtitle-options__search" data-path="subtitle_defaults.foreign_audio_search">
      <span class="subtitle-options__check">
        <Checkbox
          :input-id="`${id}-search`"
          binary
          :model-value="value.foreign_audio_search"
          :disabled="defaults.readOnly"
          :pt="{ input: { 'aria-describedby': `${id}-search-help` } }"
          data-field="foreign_audio_search"
          @update:model-value="set({ foreign_audio_search: $event === true })"
        />
        <label :for="`${id}-search`">{{ t('defaults.subtitles.foreignAudioSearch') }}</label>
      </span>
      <p :id="`${id}-search-help`" class="subtitle-options__hint">
        {{ t('defaults.subtitles.foreignAudioSearchHelp') }}
      </p>
      <IssueLines :issues="defaults.issuesAt('subtitle_defaults.foreign_audio_search')" />
    </div>
    <Field
      class="subtitle-options__burn"
      :label="t('defaults.subtitles.burnIn')"
      :help="t('defaults.subtitles.burnInHelp')"
      path="subtitle_defaults.burn_in"
      :issues="defaults.issuesAt('subtitle_defaults.burn_in')"
      stacked
    >
      <template #default="{ id: inputId, labelId, invalid }">
        <Select
          :input-id="inputId"
          :ariaLabelledby="labelId"
          :invalid="invalid"
          :model-value="value.burn_in"
          :options="choices.burnIn"
          option-label="label"
          option-value="value"
          :disabled="defaults.readOnly"
          fluid
          data-field="burn_in"
          @update:model-value="set({ burn_in: $event })"
        />
      </template>
    </Field>
  </div>
</template>

<style scoped>
.subtitle-options {
  display: grid;
  gap: var(--rf-space-4);
}

.subtitle-options__search {
  display: grid;
  gap: var(--rf-space-1);
}

.subtitle-options__check {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.subtitle-options__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.subtitle-options__burn {
  max-width: 28rem;
}
</style>
