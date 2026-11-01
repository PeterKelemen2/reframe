<script setup lang="ts">
import { watch } from 'vue'
import { RouterView } from 'vue-router'

import DefaultsDialog from '@/components/defaults/DefaultsDialog.vue'
import PowerBanner from '@/components/queue/PowerBanner.vue'
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
    <div class="app-shell__main">
      <!-- Above every view: a when-done countdown must be seen and cancelled wherever the user is. -->
      <PowerBanner />
      <RouterView />
    </div>
  </div>
  <LoginScreen v-else-if="system.phase === 'login'" />
  <BootScreen v-else :offline="system.phase === 'offline'" />
  <ShellToasts />
  <FileBrowserDialog />
  <DefaultsDialog v-if="system.phase === 'ready'" />
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
}

.app-shell__main {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  height: 100vh;
}

/* Each view fills what the banner leaves; a view's own height would push the page past the window. */
.app-shell__main > :deep(main) {
  flex: 1 1 0;
  min-width: 0;
  min-height: 0;
  height: auto;
}
</style>
