<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { CodecInfo } from './types'

/** The commercial name; FFmpeg's codec, its long name and the profile in the tooltip. */
const props = defineProps<{ stream: CodecInfo }>()

const { t } = useI18n()

const name = computed(() => props.stream.display_codec || props.stream.codec || null)

const tooltip = computed(() => {
  const { codec, codec_long: long, profile } = props.stream
  const lines = [
    codec ? t('base.codec.raw', { codec }) : null,
    long ? t('base.codec.long', { long }) : null,
    profile ? t('base.codec.profile', { profile }) : null,
  ].filter((line) => line !== null)
  return lines.length > 0 ? lines.join('\n') : undefined
})
</script>

<template>
  <span
    v-tooltip.top="tooltip"
    class="rf-codec-label"
    :class="{ 'rf-codec-label--unknown': name === null }"
  >
    {{ name ?? t('base.codec.unknown') }}
  </span>
</template>

<style scoped>
.rf-codec-label {
  font-weight: var(--rf-font-weight-bold);
  white-space: nowrap;
}

.rf-codec-label--unknown {
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-normal);
}
</style>
