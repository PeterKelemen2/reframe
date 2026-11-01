<script setup lang="ts">
import Message from 'primevue/message'
import { computed, nextTick, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppearanceSection from '@/components/settings/AppearanceSection.vue'
import EncodersSection from '@/components/settings/EncodersSection.vue'
import LanguagesSection from '@/components/settings/LanguagesSection.vue'
import OutputSection from '@/components/settings/OutputSection.vue'
import QueueSection from '@/components/settings/QueueSection.vue'
import ToolsSection from '@/components/settings/ToolsSection.vue'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const system = useSystemStore()
const settings = useSettingsStore()

const SECTIONS = ['tools', 'encoders', 'output', 'languages', 'queue', 'appearance'] as const
type SectionId = (typeof SECTIONS)[number]

function sectionTitle(id: SectionId): string {
  switch (id) {
    case 'tools':
      return t('settings.tools.title')
    case 'encoders':
      return t('settings.encoders.title')
    case 'output':
      return t('settings.output.title')
    case 'languages':
      return t('settings.languages.title')
    case 'queue':
      return t('settings.queue.title')
    case 'appearance':
      return t('settings.appearance.title')
  }
}

const readOnly = computed(() => system.info?.settings_read_only === true)
/** The sections need the server's tools and the settings. */
const ready = computed(() => system.info !== null && settings.settings !== null)

/** `/settings#tools` (the first-run screen's *Choose path*) moves the focus to that section. */
async function focusHash(): Promise<void> {
  const id = route.hash.slice(1)
  if (!(SECTIONS as readonly string[]).includes(id)) return
  await nextTick()
  const target = document.getElementById(`settings-${id}`)
  target?.focus()
  target?.scrollIntoView({ block: 'start' })
}

async function go(id: SectionId): Promise<void> {
  if (route.hash === `#${id}`) await focusHash()
  else await router.replace({ hash: `#${id}` })
}

onMounted(focusHash)
watch([() => route.hash, ready], focusHash)
</script>

<template>
  <main class="settings-view" data-view="settings">
    <header class="settings-view__header">
      <h1 class="settings-view__title">{{ t('app.views.settings') }}</h1>
      <nav class="settings-view__nav" :aria-label="t('settings.sections')">
        <a
          v-for="id in SECTIONS"
          :key="id"
          :href="`#${id}`"
          class="settings-view__link"
          :data-section-link="id"
          @click.prevent="go(id)"
        >
          {{ sectionTitle(id) }}
        </a>
      </nav>
    </header>

    <div class="settings-view__body">
      <div class="settings-view__content">
        <Message v-if="readOnly" severity="warn" data-field="read-only">
          {{ t('settings.readOnly') }}
        </Message>
        <p v-if="!ready" class="settings-view__loading" role="status">
          {{ t('settings.loading') }}
        </p>

        <div
          v-for="id in ready ? SECTIONS : []"
          :id="`settings-${id}`"
          :key="id"
          class="settings-view__section"
          tabindex="-1"
          :data-section="id"
        >
          <ToolsSection v-if="id === 'tools'" />
          <EncodersSection v-else-if="id === 'encoders'" />
          <OutputSection v-else-if="id === 'output'" />
          <LanguagesSection v-else-if="id === 'languages'" />
          <QueueSection v-else-if="id === 'queue'" />
          <AppearanceSection v-else />
        </div>
      </div>
    </div>
  </main>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.settings-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-5);
  padding: var(--rf-space-2) var(--rf-space-4);
  border-bottom: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.settings-view__title {
  margin: 0;
  font-size: var(--rf-font-size-lg);
}

.settings-view__nav {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1) var(--rf-space-3);
}

.settings-view__link {
  padding: var(--rf-space-1) var(--rf-space-2);
  border-radius: var(--rf-radius-sm);
  color: var(--rf-color-text-muted);
  text-decoration: none;
}

.settings-view__link:hover {
  background: var(--rf-color-surface-hover);
  color: var(--rf-color-text);
}

.settings-view__body {
  flex: 1;
  overflow-y: auto;
}

.settings-view__content {
  display: grid;
  gap: var(--rf-space-6);
  max-width: 64rem;
  margin-inline: auto;
  padding: var(--rf-space-5) var(--rf-space-5) var(--rf-space-6);
}

.settings-view__section {
  scroll-margin-top: var(--rf-space-4);
}

.settings-view__section:focus-visible {
  outline-offset: var(--rf-space-2);
}

.settings-view__loading {
  margin: 0;
  color: var(--rf-color-text-muted);
}
</style>
