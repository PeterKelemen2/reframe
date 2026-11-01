<script setup lang="ts">
import Checkbox from 'primevue/checkbox'
import Select from 'primevue/select'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import Field from '@/components/base/Field.vue'
import { useDefaultsStore } from '@/stores/defaults'
import { useSystemStore } from '@/stores/system'

import { PASSTHRU, useCodecOptions } from './codecs'
import IssueLines from './IssueLines.vue'
import { PASSTHRU_CODECS, type PassthruCodec } from './model'

/** Which source codecs may be passed through, and the encoder when one may not. */
const { t } = useI18n()
const defaults = useDefaultsStore()
const system = useSystemStore()
const codecs = useCodecOptions()
const id = useId()

const policy = computed(() => defaults.audio?.passthru ?? { allowed: [], fallback_encoder: 'aac' })
const allowed = computed(() => policy.value.allowed ?? [])
const fallbackOptions = computed(() =>
  codecs.options(policy.value.fallback_encoder).filter((option) => option.value !== PASSTHRU),
)

function label(codec: PassthruCodec): string {
  return system.definitions?.passthru_codecs?.[codec]?.label ?? codec
}

function setAllowed(codec: PassthruCodec, on: boolean): void {
  if (defaults.audio === null) return
  // The list keeps the canonical order, whatever order the boxes are ticked in.
  const next = PASSTHRU_CODECS.filter((each) =>
    each === codec ? on : allowed.value.includes(each),
  )
  defaults.setAudio({ ...defaults.audio, passthru: { ...policy.value, allowed: next } })
}

function setFallback(encoder: string): void {
  if (defaults.audio === null || encoder === policy.value.fallback_encoder) return
  defaults.setAudio({ ...defaults.audio, passthru: { ...policy.value, fallback_encoder: encoder } })
}
</script>

<template>
  <div class="defaults-passthru">
    <fieldset class="defaults-passthru__codecs" data-path="audio_defaults.passthru.allowed">
      <legend class="defaults-passthru__legend">{{ t('defaults.passthru.allowed') }}</legend>
      <span v-for="codec in PASSTHRU_CODECS" :key="codec" class="defaults-passthru__codec">
        <Checkbox
          :input-id="`${id}-${codec}`"
          binary
          :model-value="allowed.includes(codec)"
          :disabled="defaults.readOnly"
          :data-codec="codec"
          @update:model-value="setAllowed(codec, $event === true)"
        />
        <label :for="`${id}-${codec}`">{{ label(codec) }}</label>
      </span>
      <IssueLines
        class="defaults-passthru__issues"
        :issues="defaults.issuesAt('audio_defaults.passthru.allowed')"
      />
    </fieldset>
    <Field
      class="defaults-passthru__fallback"
      :label="t('defaults.passthru.fallback')"
      :help="t('defaults.passthru.fallbackHelp')"
      path="audio_defaults.passthru.fallback_encoder"
      :issues="defaults.issuesAt('audio_defaults.passthru.fallback_encoder')"
      stacked
    >
      <template #default="{ id: inputId, labelId, invalid }">
        <Select
          :input-id="inputId"
          :ariaLabelledby="labelId"
          :invalid="invalid"
          :model-value="policy.fallback_encoder"
          :options="fallbackOptions"
          option-label="label"
          option-value="value"
          :disabled="defaults.readOnly"
          fluid
          data-field="fallback"
          @update:model-value="setFallback"
        />
      </template>
    </Field>
  </div>
</template>

<style scoped>
.defaults-passthru {
  display: grid;
  gap: var(--rf-space-4);
}

.defaults-passthru__codecs {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2) var(--rf-space-4);
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.defaults-passthru__legend {
  margin-bottom: var(--rf-space-2);
  padding: 0;
  font-weight: var(--rf-font-weight-medium);
}

.defaults-passthru__codec {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.defaults-passthru__issues {
  flex-basis: 100%;
}

.defaults-passthru__fallback {
  max-width: 20rem;
}
</style>
