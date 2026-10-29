<script setup lang="ts">
import { FolderOpen } from '@lucide/vue'
import { useLocalStorage } from '@vueuse/core'
import Button from 'primevue/button'
import { computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import PresetPicker from '@/components/presets/PresetPicker.vue'
import EditorTabs from '@/components/shell/EditorTabs.vue'
import FirstRunScreen from '@/components/shell/FirstRunScreen.vue'
import { focusLost, focusWorkspace } from '@/components/shell/focus'
import { fileName, formatDuration } from '@/components/shell/format'
import PreviewPanel from '@/components/shell/PreviewPanel.vue'
import StatusBar from '@/components/shell/StatusBar.vue'
import SourcesPanel from '@/components/sources/SourcesPanel.vue'
import { useValidation } from '@/composables/useValidation'
import { platform } from '@/platform'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const system = useSystemStore()
const sources = useSourcesStore()

useValidation()

const previewCollapsed = useLocalStorage('reframe.workspace.previewCollapsed', false)

const title = computed(() => {
  const entry = sources.active
  return entry ? fileName(entry.path) : null
})
const duration = computed(() => formatDuration(sources.active?.source?.container?.duration))

// The first source replaces the empty state's button with the tabs, and removing the last one
// brings the button back: the focused element goes away with it.
watch(
  () => sources.active !== null,
  () => {
    if (focusLost()) focusWorkspace()
  },
  { flush: 'post' },
)

async function open(): Promise<void> {
  try {
    await sources.pick()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
  // The file dialog gives the focus back to this button, which the new source has replaced.
  await nextTick()
  if (focusLost()) focusWorkspace()
}
</script>

<template>
  <main class="workspace" :data-platform="platform.kind">
    <FirstRunScreen v-if="system.ffmpegProblem !== null" />
    <template v-else>
      <header class="workspace__header">
        <div class="workspace__source">
          <h1 class="workspace__title" data-field="title">
            {{ title ?? t('shell.workspace.noSource') }}
          </h1>
          <span v-if="duration" class="workspace__duration" data-field="duration">
            {{ duration }}
          </span>
        </div>
        <PresetPicker />
      </header>
      <div
        class="workspace__columns"
        :class="{ 'workspace__columns--preview-collapsed': previewCollapsed }"
      >
        <SourcesPanel />
        <section class="workspace__editor" :aria-label="t('shell.workspace.tabs')">
          <EditorTabs v-if="sources.active !== null" />
          <div v-else class="workspace__empty" data-state="empty">
            <FolderOpen class="workspace__empty-icon" :size="40" aria-hidden="true" />
            <h2 class="workspace__empty-title">{{ t('shell.workspace.emptyTitle') }}</h2>
            <p class="workspace__empty-text">{{ t('shell.workspace.emptyText') }}</p>
            <Button
              class="workspace__open"
              :label="t('shell.workspace.open')"
              aria-keyshortcuts="Control+O"
              @click="open"
            >
              <template #icon>
                <FolderOpen :size="18" aria-hidden="true" />
              </template>
            </Button>
            <p class="workspace__empty-text">
              <i18n-t keypath="shell.workspace.emptyShortcut" tag="span" scope="global">
                <template #key>
                  <kbd>{{ t('shell.keys.open') }}</kbd>
                </template>
              </i18n-t>
            </p>
          </div>
        </section>
        <PreviewPanel v-model:collapsed="previewCollapsed" />
      </div>
      <StatusBar />
    </template>
  </main>
</template>

<style scoped>
.workspace {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.workspace__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--rf-space-2) var(--rf-space-4);
  padding: var(--rf-space-2) var(--rf-space-4);
  border-bottom: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.workspace__source {
  display: flex;
  align-items: baseline;
  gap: var(--rf-space-3);
  min-width: 0;
}

.workspace__title {
  overflow: hidden;
  margin: 0;
  font-size: var(--rf-font-size-lg);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace__duration {
  color: var(--rf-color-text-muted);
  font-variant-numeric: tabular-nums;
}

.workspace__columns {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(14rem, 18rem) minmax(0, 1fr) minmax(16rem, 24rem);
  min-height: 0;
}

.workspace__columns--preview-collapsed {
  grid-template-columns: minmax(14rem, 18rem) minmax(0, 1fr) 3rem;
}

.workspace__columns > :deep(*) {
  min-height: 0;
  overflow: auto;
}

.workspace__columns > :deep(.sources-panel) {
  border-right: 1px solid var(--rf-color-border);
}

.workspace__editor {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.workspace__empty {
  display: grid;
  flex: 1;
  align-content: center;
  justify-items: center;
  gap: var(--rf-space-3);
  padding: var(--rf-space-6) var(--rf-space-4);
  text-align: center;
}

.workspace__empty-icon {
  color: var(--rf-color-text-muted);
}

.workspace__empty-title {
  margin: 0;
  font-size: var(--rf-font-size-xl);
}

.workspace__empty-text {
  max-width: 32rem;
  margin: 0;
  color: var(--rf-color-text-muted);
}

kbd {
  padding: 0 0.3em;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-sm);
  font-family: var(--rf-font-mono);
  font-size: 0.9em;
}

@media (width < 60rem) {
  .workspace__columns,
  .workspace__columns--preview-collapsed {
    grid-template-columns: minmax(0, 1fr);
    grid-auto-rows: auto;
    overflow: auto;
  }

  .workspace__columns > :deep(.sources-panel) {
    border-right: none;
    border-bottom: 1px solid var(--rf-color-border);
  }
}
</style>
