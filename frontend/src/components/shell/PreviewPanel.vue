<script setup lang="ts">
import { PanelRightClose, PanelRightOpen } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { onScopeDispose, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import PreviewClip from '@/components/clip/PreviewClip.vue'
import type { EditorTabId } from '@/components/editor/tabs/registry'
import FrameViewer from '@/components/media/FrameViewer.vue'
import { isTextField } from '@/editor/focus'
import { usePreviewStore, type ViewMode } from '@/stores/preview'
import { useUiStore } from '@/stores/ui'

const collapsed = defineModel<boolean>('collapsed', { required: true })

const { t } = useI18n()
const contentId = useId()
const preview = usePreviewStore()
const ui = useUiStore()

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

watch(
  collapsed,
  (hidden) => {
    preview.panelOpen = !hidden
  },
  { immediate: true },
)
onScopeDispose(() => {
  preview.panelOpen = false
})

/** A focused picture wider than its stage scrolls with the arrow keys. */
function scrollsSideways(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    target.dataset.field === 'stage' &&
    target.scrollWidth > target.clientWidth
  )
}

/** `←` / `→` step through the frames, except where the arrow keys already do something. */
function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) {
    return
  }
  const target = event.target
  if (isTextField(target) || scrollsSideways(target)) return
  if (
    target instanceof Element &&
    target.closest('[data-crop-handle], [role="slider"], input[type="range"]') !== null
  ) {
    return
  }
  event.preventDefault()
  preview.step(event.key === 'ArrowRight' ? 1 : -1)
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
        v-tooltip.left="collapsed ? t('shell.preview.show') : t('shell.preview.hide')"
        class="preview-panel__toggle"
        text
        severity="secondary"
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
    <div v-show="!collapsed" :id="contentId" class="preview-panel__content" @keydown="onKeydown">
      <FrameViewer />
      <PreviewClip />
    </div>
  </aside>
</template>

<style scoped>
.preview-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border-left: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.preview-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-2) var(--rf-space-2) var(--rf-space-3);
}

.preview-panel--collapsed .preview-panel__header {
  justify-content: center;
  padding-inline: 0;
}

.preview-panel__title {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.preview-panel__content {
  flex: 1;
  overflow: auto;
  padding: var(--rf-space-3);
}
</style>
