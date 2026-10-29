<script setup lang="ts">
defineProps<{
  /** Already translated. */
  title: string
  collapsible?: boolean
}>()

const collapsed = defineModel<boolean>('collapsed', { default: false })

defineSlots<{ default(): unknown; actions?(): unknown }>()
</script>

<template>
  <section class="section" :data-collapsed="collapsed">
    <h2>{{ title }}</h2>
    <slot name="actions" />
    <slot />
  </section>
</template>
