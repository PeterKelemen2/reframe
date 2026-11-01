<script setup lang="ts">
import { PanelRightClose, PanelRightOpen } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { useId } from 'vue'
import { useI18n } from 'vue-i18n'

const collapsed = defineModel<boolean>('collapsed', { required: true })

const { t } = useI18n()
const contentId = useId()
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
    <div v-show="!collapsed" :id="contentId" class="preview-panel__content">
      <p class="preview-panel__note">{{ t('shell.preview.later') }}</p>
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

.preview-panel__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
