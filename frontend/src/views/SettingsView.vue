<script setup lang="ts">
import Message from 'primevue/message'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppearanceSection from '@/components/settings/AppearanceSection.vue'
import DesktopSection from '@/components/settings/DesktopSection.vue'
import DiagnosticsSection from '@/components/settings/DiagnosticsSection.vue'
import EncodersSection from '@/components/settings/EncodersSection.vue'
import LanguagesSection from '@/components/settings/LanguagesSection.vue'
import MenuEntrySection from '@/components/settings/MenuEntrySection.vue'
import OutputSection from '@/components/settings/OutputSection.vue'
import PreviewSection from '@/components/settings/PreviewSection.vue'
import QueueSection from '@/components/settings/QueueSection.vue'
import ToolsSection from '@/components/settings/ToolsSection.vue'
import { platform } from '@/platform'
import type { DesktopMenuEntry } from '@/platform/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const system = useSystemStore()
const settings = useSettingsStore()

const ALL_SECTIONS = [
  'tools',
  'encoders',
  'output',
  'languages',
  'preview',
  'queue',
  'appearance',
  'diagnostics',
  'desktop',
  'menu',
] as const
type SectionId = (typeof ALL_SECTIONS)[number]
/** The AppImage's menu entry; `null` outside an AppImage. */
const menuEntry = ref<DesktopMenuEntry | null>(null)
/** The desktop app's own settings exist only there, the menu entry only in its AppImage. */
const SECTIONS = computed<readonly SectionId[]>(() =>
  ALL_SECTIONS.filter(
    (id) =>
      (id !== 'desktop' || platform.desktop !== null) &&
      (id !== 'menu' || menuEntry.value !== null),
  ),
)

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
    case 'preview':
      return t('settings.preview.title')
    case 'queue':
      return t('settings.queue.title')
    case 'appearance':
      return t('settings.appearance.title')
    case 'desktop':
      return t('window.settings.title')
    case 'menu':
      return t('menuEntry.settings.title')
    case 'diagnostics':
      return t('settings.diagnostics.title')
  }
}

const readOnly = computed(() => system.info?.settings_read_only === true)
/** The sections need the server's tools and the settings. */
const ready = computed(() => system.info !== null && settings.settings !== null)

/** Moves the focus to the section that the hash names. */
async function focusHash(): Promise<void> {
  const id = route.hash.slice(1)
  if (!(SECTIONS.value as readonly string[]).includes(id)) return
  await nextTick()
  const target = document.getElementById(`settings-${id}`)
  target?.focus()
  target?.scrollIntoView({ block: 'start' })
}

async function go(id: SectionId): Promise<void> {
  if (route.hash === `#${id}`) await focusHash()
  else await router.replace({ hash: `#${id}` })
}

async function readMenuEntry(): Promise<void> {
  try {
    const entry = await platform.desktop?.menuEntry()
    if (entry?.appimage != null) menuEntry.value = entry
  } catch (error) {
    console.error('platform.desktop.menuEntry failed', error)
  }
}

onMounted(focusHash)
onMounted(readMenuEntry)
watch([() => route.hash, ready, menuEntry], focusHash)
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
          <PreviewSection v-else-if="id === 'preview'" />
          <QueueSection v-else-if="id === 'queue'" />
          <AppearanceSection v-else-if="id === 'appearance'" />
          <DesktopSection
            v-else-if="id === 'desktop' && platform.desktop !== null"
            :shell="platform.desktop"
          />
          <MenuEntrySection
            v-else-if="id === 'menu' && platform.desktop !== null && menuEntry !== null"
            :shell="platform.desktop"
            :entry="menuEntry"
          />
          <DiagnosticsSection v-else-if="id === 'diagnostics'" />
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
  font-size: var(--rf-text-title);
  line-height: var(--rf-line-height-tight);
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
  gap: var(--rf-space-4);
  max-width: 64rem;
  margin-inline: auto;
  padding: var(--rf-space-5) var(--rf-space-5) var(--rf-space-6);
}

/* Each section is a hairline panel on the ground, as the workspace's cards. */
.settings-view__section {
  padding: var(--rf-space-4) var(--rf-space-5) var(--rf-space-5);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-lg);
  background: var(--rf-color-surface);
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
