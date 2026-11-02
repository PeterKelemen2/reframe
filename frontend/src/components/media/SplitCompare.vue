<script setup lang="ts">
// Stub: before and after of one frame, split by a slider or side by side.
import type { FrameLink, Geometry } from '@/api/types'

defineProps<{
  /** The source frame. */
  before: FrameLink
  /** The output picture at the same time: a rendered output frame or a frame of a clip. */
  after: FrameLink
  /** The job's geometry: `before` is shown cropped, turned and flipped as `after` is. */
  geometry: Geometry | null
  layout?: 'split' | 'side'
}>()
</script>

<template>
  <div class="split-compare" data-stub="split-compare" />
</template>
