<script setup lang="ts">
/**
 * The editor's job's output name (the Summary tab's Output card): the template or a manual
 * name, the parsed-name panel with per-file field overrides, and the live preview of the
 * output path. Reads and writes the editor store (`/output/naming`, `/output/path`).
 */
defineProps<{ disabled?: boolean }>()
</script>

<template>
  <div class="job-naming-editor" />
</template>
