<script setup lang="ts">
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NamingVariable } from '@/stores/system'

/** The template variables as buttons with their value for the current source; a click inserts one. */
const props = defineProps<{
  variables: NamingVariable[]
  /** Each variable's value for the current source (`NameResult.variables`); `null`: no source. */
  values: Record<string, string> | null
  disabled?: boolean
}>()

const emit = defineEmits<{ insert: [name: string] }>()

const { t } = useI18n()

const GROUPS: NamingVariable['group'][] = ['name', 'media', 'handbrake']

function groupTitle(group: NamingVariable['group']): string {
  switch (group) {
    case 'name':
      return t('naming.chips.groupName')
    case 'media':
      return t('naming.chips.groupMedia')
    case 'handbrake':
      return t('naming.chips.groupHandbrake')
  }
}

const groups = computed(() =>
  GROUPS.map((group) => ({
    group,
    title: groupTitle(group),
    variables: props.variables.filter((variable) => variable.group === group),
  })).filter((entry) => entry.variables.length > 0),
)

function braced(name: string): string {
  return `{${name}}`
}

function valueOf(name: string): string | null {
  const value = props.values?.[name]
  return value === undefined || value === '' ? null : value
}

function label(variable: NamingVariable): string {
  const value = valueOf(variable.name)
  const name = braced(variable.name)
  return value === null
    ? t('naming.chips.insertEmpty', { name })
    : t('naming.chips.insert', { name, value })
}
</script>

<template>
  <div class="naming-chips">
    <div v-for="entry in groups" :key="entry.group" class="naming-chips__group">
      <span class="naming-chips__title">{{ entry.title }}</span>
      <ul class="naming-chips__list">
        <li v-for="variable in entry.variables" :key="variable.name">
          <button
            v-tooltip.top="variable.description"
            type="button"
            class="naming-chip"
            :data-variable="variable.name"
            :disabled="disabled"
            :aria-label="label(variable)"
            @click="emit('insert', variable.name)"
          >
            <code class="naming-chip__name">{{ braced(variable.name) }}</code
            >{{ ' '
            }}<span
              v-if="values !== null"
              class="naming-chip__value"
              :class="{ 'naming-chip__value--empty': valueOf(variable.name) === null }"
              >{{ valueOf(variable.name) ?? t('naming.chips.empty') }}</span
            >
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.naming-chips {
  display: grid;
  gap: var(--rf-space-2);
}

.naming-chips__group {
  display: grid;
  gap: var(--rf-space-1);
}

.naming-chips__title {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.naming-chips__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.naming-chips__list li {
  min-width: 0;
  max-width: 100%;
}

.naming-chip {
  display: inline-flex;
  align-items: baseline;
  gap: var(--rf-space-1);
  max-width: 100%;
  overflow: hidden;
  padding: 0.15rem var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-pill);
  background: var(--rf-color-surface);
  color: var(--rf-color-text);
  font: inherit;
  font-size: var(--rf-font-size-sm);
  cursor: pointer;
}

.naming-chip:hover:not(:disabled) {
  background: var(--rf-color-surface-hover);
}

.naming-chip:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 1px;
}

.naming-chip:disabled {
  cursor: default;
  opacity: 0.6;
}

.naming-chip__name {
  font-family: var(--rf-font-mono);
}

.naming-chip__value {
  min-width: 0;
  max-width: 16rem;
  overflow: hidden;
  color: var(--rf-color-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.naming-chip__value--empty {
  color: var(--rf-color-text-muted);
  font-style: italic;
}
</style>
