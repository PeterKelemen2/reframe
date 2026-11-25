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
    <slot name="above-panels" />
    <TabPanels ref="panels" class="editor-tabs__panels">
      <TabPanel v-for="tab in EDITOR_TABS" :key="tab.id" :value="tab.id" :data-panel="tab.id">
        <component :is="components[tab.id]" />
      </TabPanel>
    </TabPanels>
  </Tabs>
</template>

<style scoped>
.editor-tabs {
  /* Text tabs: the open one in ink (paper in dark) over a 2px rule, the others muted. One
     weight for all, so a tab keeps its width when it opens. */
  --p-tabs-active-bar-height: 2px;
  --p-tabs-tab-active-color: var(--rf-color-text);
  --p-tabs-active-bar-background: var(--rf-color-text);
  --p-tabs-tab-font-weight: var(--rf-font-weight-medium);
  /* The cards lie on the cool-white ground (blue-black in dark), not on a panel of their own
     colour; the tab strip stays on the panel. */
  --p-tabs-tabpanel-background: var(--rf-color-bg);

  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}

/* All eight tabs fit beside the open preview at 1440 px. The same width everywhere keeps each
   tab in its place when a tab opens or closes the preview. */
.editor-tabs :deep([role='tab']) {
  padding-block: 0.6875rem;
  padding-inline: 0.5rem;
}

/* The first label lines up with the panels' content. */
.editor-tabs :deep([role='tablist']) {
  padding-inline-start: 0.625rem;
}

/* A size container: a tab can size itself by the panels' height. */
.editor-tabs__panels {
  container-type: size;
  flex: 1;
  min-height: 0;
  padding-bottom: 0;
  overflow: auto;
}

/* Firefox gives the scroller a Tab stop of its own; PrimeVue's panels have no outline. Inside, as
   the column around it clips. */
.editor-tabs__panels:focus-visible {
  outline: var(--p-focus-ring-width) var(--p-focus-ring-style) var(--p-focus-ring-color);
  outline-offset: calc(-1 * var(--p-focus-ring-width));
}

/* The bottom padding belongs to the panels, except the one that ends in the drawer. */
.editor-tabs__panels :deep([role='tabpanel']) {
  padding-bottom: 1.125rem;
}

.editor-tabs__panels :deep([data-panel='video']) {
  padding-bottom: 0;
}
</style>
