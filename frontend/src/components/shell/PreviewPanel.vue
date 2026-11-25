<script setup lang="ts">
import { Maximize2, PanelRightClose, PanelRightOpen, PictureInPicture2 } from '@lucide/vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import vTooltip from 'primevue/tooltip'
import { onScopeDispose, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import PreviewClip from '@/components/clip/PreviewClip.vue'
import type { EditorTabId } from '@/components/editor/tabs/registry'
import FrameViewer from '@/components/media/FrameViewer.vue'
import ProgrammeStrip from '@/components/strip/ProgrammeStrip.vue'
import { platform } from '@/platform'
import { usePreviewStore, type ViewMode } from '@/stores/preview'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import { shareWithPreviewWindow, stepOnArrowKeys } from './previewWindow'

const collapsed = defineModel<boolean>('collapsed', { required: true })

const { t } = useI18n()
const contentId = useId()
const preview = usePreviewStore()
const ui = useUiStore()
const toasts = useToastStore()
// Only the desktop app has a preview window to share with.
const { detached } = platform.desktop === null ? { detached: ref(false) } : shareWithPreviewWindow()
/** The browser's large preview: a modal on this page, with the same stores. */
const enlarged = ref(false)
watch(
  () => preview.sourceId,
  (id) => {
    if (id === null) enlarged.value = false
  },
)

/** The view a tab shows; on the other tabs the panel shows the view the user chose. */
const TAB_VIEWS: Partial<Record<EditorTabId, ViewMode>> = { dimensions: 'source', filters: 'split' }
const chosen = ref<ViewMode>(preview.viewMode)

watch(
  () => preview.viewMode,
  (mode) => {
    if (TAB_VIEWS[ui.activeTab] === undefined) chosen.value = mode
  },
)
watch(
  () => ui.activeTab,
  (tab) => {
    preview.viewMode = TAB_VIEWS[tab] ?? chosen.value
  },
  { immediate: true },
)

// While detached, the preview window asks for the output frames; the large preview does too.
watch(
  () => (!collapsed.value && !detached.value) || enlarged.value,
  (open) => {
    preview.panelOpen = open
  },
  { immediate: true },
)
onScopeDispose(() => {
  preview.panelOpen = false
})

/** Opens the preview window on the shown file, or focuses it (an open one needs no file). */
async function openWindow(): Promise<void> {
  if (platform.desktop === null) return
  try {
    await platform.desktop.openPreviewWindow(preview.sourceId ?? '')
  } catch (error) {
    toasts.push({ severity: 'error', summary: t('window.preview.failed'), detail: String(error) })
  }
}
</script>

<template>
  <aside
    class="preview-panel"
    :class="{ 'preview-panel--collapsed': collapsed }"
    :aria-label="t('shell.preview.title')"
  >
    <div class="preview-panel__header">
      <h2 v-if="!collapsed" class="preview-panel__title">{{ t('shell.preview.title') }}</h2>
      <Button
        v-if="platform.desktop !== null && !collapsed"
        v-tooltip.left="t('window.preview.detach')"
        class="preview-panel__detach"
        text
        severity="secondary"
        :aria-label="t('window.preview.detach')"
        :disabled="preview.sourceId === null"
        data-action="detach"
        @click="openWindow"
      >
        <template #icon>
          <PictureInPicture2 :size="18" aria-hidden="true" />
        </template>
      </Button>
      <Button
        v-if="platform.desktop === null && !collapsed"
        v-tooltip.left="t('window.preview.enlarge')"
        class="preview-panel__detach"
        text
        severity="secondary"
        :aria-label="t('window.preview.enlarge')"
        :disabled="preview.sourceId === null"
        data-action="enlarge"
        @click="enlarged = true"
      >
        <template #icon>
          <Maximize2 :size="18" aria-hidden="true" />
        </template>
      </Button>
      <Button
        v-tooltip.left="collapsed ? t('shell.preview.show') : t('shell.preview.hide')"
        class="preview-panel__toggle"
        text
        severity="secondary"
        :label="collapsed ? t('shell.preview.title') : undefined"
        :aria-label="collapsed ? t('shell.preview.show') : t('shell.preview.hide')"
        :aria-expanded="!collapsed"
        :aria-controls="contentId"
        @click="collapsed = !collapsed"
      >
        <template #icon>
          <PanelRightOpen v-if="collapsed" :size="18" aria-hidden="true" />
          <PanelRightClose v-else :size="18" aria-hidden="true" />
        </template>
      </Button>
    </div>
    <div
      v-show="!collapsed"
      :id="contentId"
      class="preview-panel__content"
      @keydown="stepOnArrowKeys"
    >
      <template v-if="detached || enlarged">
        <div v-if="detached" class="preview-panel__detached" data-state="detached">
          <p>{{ t('window.preview.detached') }}</p>
          <Button
            :label="t('window.preview.focus')"
            severity="secondary"
            size="small"
            data-action="focus-window"
            @click="openWindow"
          />
        </div>
        <p v-else class="preview-panel__detached" data-state="enlarged">
          {{ t('window.preview.enlarged') }}
        </p>
        <ProgrammeStrip v-if="!collapsed" />
      </template>
      <template v-else>
        <FrameViewer>
          <template #programme>
            <ProgrammeStrip v-if="!collapsed" />
          </template>
        </FrameViewer>
        <PreviewClip />
      </template>
    </div>
    <Dialog
      v-model:visible="enlarged"
      modal
      maximizable
      class="preview-dialog"
      :header="t('shell.preview.title')"
      :style="{ width: 'min(100rem, calc(100vw - 2rem))' }"
      data-dialog="preview"
    >
      <div class="preview-dialog__content" @keydown="stepOnArrowKeys">
        <FrameViewer />
        <PreviewClip />
      </div>
    </Dialog>
  </aside>
</template>

<style scoped>
.preview-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-left: 1px solid var(--rf-color-border);
  background: var(--rf-color-booth);
}

.preview-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--rf-space-2);
  padding: var(--rf-space-3) var(--rf-space-2) 0 var(--rf-space-4);
}

.preview-panel--collapsed .preview-panel__header {
  justify-content: center;
  padding-inline: 0;
}

/* The strip names what it opens: the label runs down it under the icon. */
.preview-panel--collapsed .preview-panel__toggle {
  gap: var(--rf-space-2);
  padding-block: var(--rf-space-3);
  writing-mode: vertical-rl;
}

.preview-panel__title {
  flex: 1;
  margin: 0;
  font-size: var(--rf-text-heading);
  font-weight: var(--rf-font-weight-bold);
  line-height: var(--rf-line-height-tight);
}

.preview-panel__detached {
  display: grid;
  justify-items: start;
  gap: var(--rf-space-2);
  color: var(--rf-color-text-muted);
}

.preview-panel__detached p {
  margin: 0;
}

.preview-dialog__content {
  display: grid;
  align-content: start;
  gap: var(--rf-space-3);
}

.preview-panel__content {
  display: grid;
  flex: 1;
  align-content: start;
  gap: var(--rf-space-4);
  overflow: auto;
  padding: var(--rf-space-3) var(--rf-space-4) var(--rf-space-4);
}
</style>
