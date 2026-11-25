<script setup lang="ts">
import { onScopeDispose } from 'vue'
import { useI18n } from 'vue-i18n'

import PreviewClip from '@/components/clip/PreviewClip.vue'
import FrameViewer from '@/components/media/FrameViewer.vue'
import { followMainWindow, stepOnArrowKeys } from '@/components/shell/previewWindow'
import { usePreviewStore } from '@/stores/preview'

// The route's source is where the window opened; it then shows the main window's file.
const { t } = useI18n()
const preview = usePreviewStore()

followMainWindow()
preview.panelOpen = true
onScopeDispose(() => {
  preview.panelOpen = false
})
</script>

<template>
  <main
    class="preview-window"
    :aria-label="t('shell.preview.title')"
    data-view="preview-window"
    @keydown="stepOnArrowKeys"
  >
    <FrameViewer />
    <PreviewClip />
  </main>
</template>

<style scoped>
.preview-window {
  display: grid;
  align-content: start;
  gap: var(--rf-space-3);
  height: 100vh;
  padding: var(--rf-space-3);
  overflow: auto;
  background: var(--rf-color-booth);
}
</style>
