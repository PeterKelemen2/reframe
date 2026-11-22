<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterView, useRoute, useRouter } from 'vue-router'

import { desktopBackend } from '@/api/boot'
import DefaultsDialog from '@/components/defaults/DefaultsDialog.vue'
import PowerBanner from '@/components/queue/PowerBanner.vue'
import BackendErrorScreen from '@/components/shell/BackendErrorScreen.vue'
import BootScreen from '@/components/shell/BootScreen.vue'
import LoginScreen from '@/components/shell/LoginScreen.vue'
import MenuEntryOffer from '@/components/shell/MenuEntryOffer.vue'
import NavRail from '@/components/shell/NavRail.vue'
import PrivateQueueBanner from '@/components/shell/PrivateQueueBanner.vue'
import QuitDialog from '@/components/shell/QuitDialog.vue'
import ReconnectOverlay from '@/components/shell/ReconnectOverlay.vue'
import { refocusAfterNavigation } from '@/components/shell/focus'
import ShellToasts from '@/components/shell/ShellToasts.vue'
import FileBrowserDialog from '@/components/sources/FileBrowserDialog.vue'
import { useInPlaceReload } from '@/components/summary/useInPlaceReload'
import { useOpenPaths } from '@/composables/useOpenPaths'
import { type QuitAnswer, useQuitFlow } from '@/composables/useQuitFlow'
import { useShortcuts } from '@/composables/useShortcuts'
import { useTheme } from '@/composables/useTheme'
import { platform } from '@/platform'
import { useQueueStore } from '@/stores/queue'
import { useSystemStore } from '@/stores/system'

const system = useSystemStore()
const queue = useQueueStore()
const route = useRoute()
const { n } = useI18n()

// Follows the theme and density saved in the server's settings.
useTheme()
useShortcuts()
useInPlaceReload()
useOpenPaths()
onUnmounted(refocusAfterNavigation(useRouter()))
const quit = useQuitFlow()

/** The desktop app's server restarts under a running app (before the first start: the boot screen). */
const reconnecting = computed(
  () => desktopBackend.value?.state === 'starting' && system.phase !== 'booting',
)
const privateQueue = computed(() =>
  desktopBackend.value?.state === 'ready' ? desktopBackend.value.info.privateQueue : null,
)
// `starting` carries no backend: what *Reconnecting…* says depends on the one that went away.
const lastOwned = ref(true)
watch(
  desktopBackend,
  (state) => {
    if (state?.state === 'ready') lastOwned.value = state.info.owned
  },
  { immediate: true },
)

async function retryBackend(): Promise<void> {
  await platform.desktop?.retryBackend()
}

// A failed request is a toast already; the app stays open.
function answerQuit(choice: QuitAnswer): void {
  quit.answer(choice).catch((error: unknown) => console.error('quit failed', error))
}

watch(
  () => queue.overallProgress,
  (value) =>
    platform.setTaskbarProgress(
      value,
      value === null ? null : n(value, { style: 'percent', maximumFractionDigits: 0 }),
    ),
  { immediate: true },
)
</script>

<template>
  <BackendErrorScreen
    v-if="desktopBackend?.state === 'failed'"
    :error="desktopBackend.error"
    :retry="retryBackend"
  />
  <RouterView v-else-if="system.phase === 'ready' && route.meta.bare" />
  <div v-else-if="system.phase === 'ready'" class="app-shell">
    <NavRail />
    <div class="app-shell__main">
      <!-- Above every view: a when-done countdown must be seen and cancelled wherever the user is. -->
      <PowerBanner />
      <PrivateQueueBanner v-if="privateQueue" :queue="privateQueue" />
      <RouterView />
    </div>
  </div>
  <LoginScreen v-else-if="system.phase === 'login'" />
  <BootScreen v-else :offline="system.phase === 'offline'" />
  <ReconnectOverlay v-if="reconnecting" :owned="lastOwned" />
  <ShellToasts />
  <!-- The server's file browser: the desktop app has the system's dialogs. -->
  <FileBrowserDialog v-if="platform.kind === 'web'" />
  <QuitDialog :question="quit.question.value" @answer="answerQuit" />
  <DefaultsDialog v-if="system.phase === 'ready'" />
  <MenuEntryOffer
    v-if="system.phase === 'ready' && platform.desktop !== null"
    :shell="platform.desktop"
  />
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
