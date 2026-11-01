<script setup lang="ts">
/**
 * An ordered list of languages (Settings → Languages, the defaults' languages): add through
 * `LanguagePicker`, remove, reorder by drag and by keyboard.
 */
defineProps<{
  label: string
  disabled?: boolean
}>()

defineModel<string[]>({ required: true })
</script>

<template>
  <div class="language-list-editor" />
</template>
