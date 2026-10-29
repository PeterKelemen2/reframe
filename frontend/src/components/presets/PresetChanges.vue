<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FieldChange } from '@/api/types'
import { useSystemStore } from '@/stores/system'

import { pathWords, valueWords, type Words } from './format'

/** The changes of `presets/diff`, each as its setting, the preset's value and the current one. */
const props = defineProps<{ changes: FieldChange[] }>()

const { t, tm, rt } = useI18n()
const system = useSystemStore()

const words = computed<Words>(() => {
  const fields = tm('presets.field') as Record<string, unknown>
  return {
    field: (key) => {
      const message = fields[key]
      return message === undefined ? undefined : rt(message as Parameters<typeof rt>[0])
    },
    none: t('presets.value.none'),
    empty: t('presets.value.empty'),
    on: t('presets.value.on'),
    off: t('presets.value.off'),
  }
})

function shown(path: string, value: unknown): string {
  if (typeof value === 'string' && path === 'output.container') {
    return system.definitions?.containers?.[value]?.label ?? value
  }
  if (typeof value === 'string' && /(^|\.)encoder$/.test(path)) {
    const encoders = path.startsWith('video')
      ? system.definitions?.video_encoders
      : system.definitions?.audio_encoders
    const label = encoders?.[value]?.label
    if (label !== undefined) return label
  }
  return valueWords(value, words.value)
}

const rows = computed(() =>
  props.changes.map((change, index) => ({
    key: `${change.path}:${index}`,
    kind: change.kind,
    label: pathWords(change.path, words.value),
    before: shown(change.path, change.preset_value),
    after: shown(change.path, change.value),
  })),
)
</script>

<template>
  <ul class="preset-changes" data-list="preset-changes">
    <li v-for="row in rows" :key="row.key" class="preset-changes__item" :data-kind="row.kind">
      <span class="preset-changes__field">{{ row.label }}</span>
      <span v-if="row.kind === 'added'" class="preset-changes__values">
        {{ t('presets.changes.added', { value: row.after }) }}
      </span>
      <span v-else-if="row.kind === 'removed'" class="preset-changes__values">
        {{ t('presets.changes.removed', { value: row.before }) }}
      </span>
      <span v-else class="preset-changes__values">
        <span class="preset-changes__before">{{ row.before }}</span>
        <span aria-hidden="true"> → </span>
        <span class="rf-sr-only">{{ t('presets.changes.to') }}</span>
        <span class="preset-changes__after">{{ row.after }}</span>
      </span>
    </li>
  </ul>
</template>

<style scoped>
.preset-changes {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.preset-changes__item {
  display: grid;
  gap: var(--rf-space-1);
}

.preset-changes__field {
  font-weight: var(--rf-font-weight-medium);
}

.preset-changes__values {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.preset-changes__before {
  text-decoration: line-through;
}

.preset-changes__after {
  color: var(--rf-color-text);
}
</style>
