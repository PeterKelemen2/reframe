<script setup lang="ts">
/** A language by its tag (BCP 47 or ISO 639-2): the name, the code in the tooltip; `und` or none: undetermined. */
defineProps<{ tag: string | null | undefined }>()
</script>

<template>
  <span class="language-chip" />
</template>
