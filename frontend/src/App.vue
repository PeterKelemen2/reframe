<script setup lang="ts">
import { RouterView } from 'vue-router'

import FileBrowserDialog from '@/components/sources/FileBrowserDialog.vue'
import { useShortcuts } from '@/composables/useShortcuts'

useShortcuts()
</script>

<template>
  <RouterView />
  <FileBrowserDialog />
</template>
