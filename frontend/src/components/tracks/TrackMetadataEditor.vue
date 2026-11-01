<script setup lang="ts">
/**
 * The metadata block of one output track: language, name (text or a name template) and the
 * six flags, each change one undo step in the editor's job (`/video/metadata`,
 * `/audio/{index}/metadata`, `/subtitles/{index}/metadata`).
 */
defineProps<{
  list: 'video' | 'audio' | 'subtitles'
  /** The output track's place in its list; not used for `video`. */
  index?: number
  disabled?: boolean
}>()
</script>

<template>
  <div class="track-metadata-editor" />
</template>
