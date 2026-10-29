<script setup lang="ts">
import type { CodecInfo } from './types'

/** The commercial name; FFmpeg's codec, its long name and the profile in the tooltip. */
defineProps<{ stream: CodecInfo }>()
</script>

<template>
  <span class="codec-label" />
</template>
