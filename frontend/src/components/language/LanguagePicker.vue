<script setup lang="ts">
/**
 * One language (BCP 47): a search dialog over `system.languages` by English name, native name,
 * ISO 639-1/2/3 code or full tag (region and script subtags too: `pt-BR`, `zh-Hans`), the
 * favourites of Settings → Languages first, and what is written (`Hungarian · hun · hu`).
 */
defineProps<{
  /** The accessible name when no `Field` labels it. */
  label?: string
  inputId?: string
  /** The id of the label element (`Field`'s `labelId`). */
  labelledby?: string
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  /** Offer *None* (`null`); for an output track it means "keep the source's language". */
  clearable?: boolean
}>()

defineModel<string | null>({ required: true })
</script>

<template>
  <span class="language-picker" />
</template>
