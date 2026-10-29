<script setup lang="ts">
import type { NamingOptions } from '@/api/types'

/**
 * The naming templates and options (Settings → Output, the preset editor): template fields
 * with `{` completion and variable chips, the options, and a live preview for `sourceIds`.
 */
defineProps<{
  /** Sources whose values the chips and the preview show; empty: no preview. */
  sourceIds?: string[]
  container?: 'mkv' | 'mp4' | 'webm'
  disabled?: boolean
}>()

defineModel<NamingOptions>({ required: true })
</script>

<template>
  <div class="naming-options-editor" />
</template>
