<script setup lang="ts">
import Tab from 'primevue/tab'
import TabList from 'primevue/tablist'
import TabPanel from 'primevue/tabpanel'
import TabPanels from 'primevue/tabpanels'
import Tabs from 'primevue/tabs'
import { type Component, computed, defineAsyncComponent, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { EDITOR_TABS, type EditorTabId } from '@/components/editor/tabs/registry'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const ui = useUiStore()

/** Each tab's code loads the first time the tab is shown. */
const components = Object.fromEntries(
  EDITOR_TABS.map((tab) => [tab.id, defineAsyncComponent(tab.component)]),
) as Record<EditorTabId, Component>

const active = computed({
  get: () => ui.activeTab,
  set: (value: string | number) => {
    const tab = EDITOR_TABS.find((candidate) => candidate.id === value)
    if (tab) ui.activeTab = tab.id
  },
})

const panels = useTemplateRef<{ $el: HTMLElement }>('panels')

// The panels are the one scroller of every tab: a new tab would open at the old tab's offset.
watch(active, () => {
  if (panels.value) panels.value.$el.scrollTop = 0
})
</script>

<template>
  <Tabs v-model:value="active" class="editor-tabs" lazy scrollable>
    <TabList :pt="{ tabList: { 'aria-label': t('shell.workspace.tabs') } }">
      <Tab
        v-for="tab in EDITOR_TABS"
        :key="tab.id"
        :value="tab.id"
        :data-tab="tab.id"
        :pt="{ root: { 'aria-keyshortcuts': `Control+${tab.shortcut}` } }"
      >
        {{ t(tab.labelKey) }}
      </Tab>
    </TabList>
    <TabPanels ref="panels" class="editor-tabs__panels">
      <TabPanel v-for="tab in EDITOR_TABS" :key="tab.id" :value="tab.id" :data-panel="tab.id">
        <component :is="components[tab.id]" />
      </TabPanel>
    </TabPanels>
  </Tabs>
</template>

<style scoped>
.editor-tabs {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

.editor-tabs__panels {
  flex: 1;
  min-height: 0;
  padding-bottom: 0;
  overflow: auto;
}

/*
 * A sticky drawer stops at the scroller's padding, and what scrolls under it shows in the gap.
 * The bottom padding belongs to the panels, except the one that ends in the drawer.
 */
.editor-tabs__panels :deep([role='tabpanel']) {
  padding-bottom: 1.125rem;
}

.editor-tabs__panels :deep([data-panel='video']) {
  padding-bottom: 0;
}
</style>
