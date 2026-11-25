<script setup lang="ts">
import { computed } from 'vue'

import LanguageChip from '@/components/base/LanguageChip.vue'
import { channelsText, streamLanguage, trackNumber } from '@/components/media/streams'
import type { SourceStream } from '@/components/media/streams'

/** A source track as a choice: its number, its language's mark and name, format and title. */
const props = defineProps<{ stream: SourceStream }>()

const rest = computed(() => {
  const codec = props.stream.display_codec || props.stream.codec || null
  const format =
    props.stream.kind === 'audio'
      ? [codec, channelsText(props.stream)].filter(Boolean).join(' ')
      : codec
  return [format, props.stream.title].filter((part) => part !== null && part !== '').join(' · ')
})
</script>

<template>
  <span class="stream-option">
    <span class="rf-mono stream-option__number">{{ trackNumber(stream) }}</span>
    <LanguageChip :tag="streamLanguage(stream)" />
    <span v-if="rest" class="stream-option__rest">{{ rest }}</span>
  </span>
</template>

<style scoped>
.stream-option {
  display: inline-flex;
  gap: var(--rf-space-2);
  align-items: center;
  min-width: 0;
}

.stream-option__number {
  color: var(--rf-color-text-muted);
}

.stream-option__rest {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
