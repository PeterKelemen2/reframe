<script setup lang="ts">
import { Activity, Columns3, ListVideo, LogOut, Settings, SlidersHorizontal } from '@lucide/vue'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'

import { ApiError } from '@/api/client'
import { useSystemStore } from '@/stores/system'

import ConnectionStatus from './ConnectionStatus.vue'
import ThemeSwitch from './ThemeSwitch.vue'

const { t } = useI18n()
const system = useSystemStore()

const items = computed(() => [
  { to: '/', name: 'workspace', label: t('app.views.workspace'), icon: Columns3 },
  { to: '/queue', name: 'queue', label: t('app.views.queue'), icon: ListVideo },
  { to: '/presets', name: 'presets', label: t('app.views.presets'), icon: SlidersHorizontal },
  { to: '/activity', name: 'activity', label: t('app.views.activity'), icon: Activity },
])
const settings = computed(() => ({
  to: '/settings',
  name: 'settings',
  label: t('app.views.settings'),
  icon: Settings,
}))

async function logout(): Promise<void> {
  try {
    await system.logout()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
}
</script>

<template>
  <nav class="nav-rail" :aria-label="t('shell.nav.label')">
    <ul class="nav-rail__items">
      <li v-for="item in items" :key="item.name">
        <RouterLink :to="item.to" class="nav-rail__link" :data-view="item.name">
          <component :is="item.icon" :size="20" aria-hidden="true" />
          <span class="nav-rail__label">{{ item.label }}</span>
        </RouterLink>
      </li>
    </ul>
    <div class="nav-rail__footer">
      <ConnectionStatus compact />
      <ThemeSwitch />
      <Button
        v-if="system.auth?.mode === 'password'"
        v-tooltip.right="t('shell.nav.logout')"
        class="nav-rail__button"
        text
        severity="secondary"
        :aria-label="t('shell.nav.logout')"
        @click="logout"
      >
        <template #icon>
          <LogOut :size="20" aria-hidden="true" />
        </template>
      </Button>
      <!-- Settings closes the rail, apart from the views. -->
      <ul class="nav-rail__items nav-rail__items--end">
        <li>
          <RouterLink :to="settings.to" class="nav-rail__link" :data-view="settings.name">
            <component :is="settings.icon" :size="20" aria-hidden="true" />
            <span class="nav-rail__label">{{ settings.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </nav>
</template>

<style scoped>
.nav-rail {
  display: flex;
  flex-direction: column;
  flex: none;
  justify-content: space-between;
  gap: var(--rf-space-3);
  position: sticky;
  top: 0;
  width: 5rem;
  height: 100vh;
  overflow-y: auto;
  padding: var(--rf-space-2) 0.3125rem;
  border-right: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.nav-rail__items {
  display: grid;
  gap: 0.125rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.nav-rail__items--end {
  align-self: stretch;
}

.nav-rail__link {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.2rem;
  padding: 0.5625rem 0 0.4375rem;
  border-radius: var(--rf-radius-lg);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  line-height: var(--rf-line-height-tight);
  text-align: center;
  text-decoration: none;
  transition:
    background-color var(--rf-duration),
    color var(--rf-duration);
}

.nav-rail__link:hover {
  background: var(--rf-color-surface-hover);
  color: var(--rf-color-text);
}

/* The view shown: the whole item tinted, in ink on paper or paper on ink. */
.nav-rail__link[aria-current='page'] {
  background: var(--p-highlight-background);
  color: var(--rf-color-text);
  font-weight: var(--rf-font-weight-medium);
}

.nav-rail__label {
  overflow-wrap: anywhere;
}

.nav-rail__footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--rf-space-2);
}

.nav-rail__button {
  color: var(--rf-color-text-muted);
}
</style>
