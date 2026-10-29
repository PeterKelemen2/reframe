<script setup lang="ts">
import Tab from 'primevue/tab'
import TabList from 'primevue/tablist'
import TabPanel from 'primevue/tabpanel'
import TabPanels from 'primevue/tabpanels'
import Tabs from 'primevue/tabs'
import { type Component, computed, defineAsyncComponent } from 'vue'
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
    <TabPanels class="editor-tabs__panels">
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
  overflow: auto;
}
</style>
