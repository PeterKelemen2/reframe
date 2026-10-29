<script setup lang="ts">
import { watch } from 'vue'
import { RouterView } from 'vue-router'

import BootScreen from '@/components/shell/BootScreen.vue'
import LoginScreen from '@/components/shell/LoginScreen.vue'
import NavRail from '@/components/shell/NavRail.vue'
import ShellToasts from '@/components/shell/ShellToasts.vue'
import FileBrowserDialog from '@/components/sources/FileBrowserDialog.vue'
import { useShortcuts } from '@/composables/useShortcuts'
import { useTheme } from '@/composables/useTheme'
import { platform } from '@/platform'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'

const system = useSystemStore()
const queue = useQueueStore()

// The first call starts following the theme and density saved in the server's settings.
useTheme()
useShortcuts()

watch(
  () => queue.overallProgress,
  (value) => platform.setTaskbarProgress(value),
  { immediate: true },
)
</script>

<template>
  <div v-if="system.phase === 'ready'" class="app-shell">
    <NavRail />
    <RouterView />
  </div>
  <LoginScreen v-else-if="system.phase === 'login'" />
  <BootScreen v-else :offline="system.phase === 'offline'" />
  <ShellToasts />
  <FileBrowserDialog />
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

.app-shell > :deep(main) {
  flex: 1;
  min-width: 0;
}
</style>
