<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { FieldChange } from '@/api/types'
import { useSystemStore } from '@/stores/system'

import { pathWords, valueWords, type Words } from './format'

/**
 * The changes of `presets/diff`, each as its setting, the preset's value and the current one.
 * `encoder` is the job's video encoder: a quality is shown on its scale.
 */
const props = defineProps<{ changes: FieldChange[]; encoder?: string | null }>()

const { t, tm, rt, locale } = useI18n()
const system = useSystemStore()

type Members = Record<string, unknown>

function isObject(value: unknown): value is Members {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function rateControl(value: Members, encoder: string | null | undefined): string | undefined {
  if (value.mode === 'quality') {
    const scale = encoder
      ? system.definitions?.video_encoders?.[encoder]?.rate_control?.quality?.label
      : undefined
    return t('presets.value.quality', {
      quality: [scale, value.value].filter((part) => part !== undefined && part !== '').join(' '),
    })
  }
  if (value.mode === 'bitrate' && typeof value.kbps === 'number') {
    const kbps = new Intl.NumberFormat(locale.value).format(value.kbps)
    return value.two_pass === true
      ? t('presets.value.bitrateTwoPass', { kbps })
      : t('presets.value.bitrate', { kbps })
  }
  return undefined
}

function size(value: Members): string | undefined {
  switch (value.mode) {
    case 'source':
      return t('presets.details.sizeSource')
    case 'fit':
      return t('presets.details.sizeFit', { width: value.width, height: value.height })
    case 'width':
      return t('presets.details.sizeWidth', { width: value.width })
    case 'height':
      return t('presets.details.sizeHeight', { height: value.height })
  }
  return undefined
}

/** The words of the values that are known by their path; `encoder` gives a quality its scale. */
function knownWords(
  path: string,
  value: unknown,
  encoder: string | null | undefined,
): string | undefined {
  if (path === 'naming') {
    if (value === null) return t('presets.value.settingsNaming')
    if (isObject(value) && typeof value.movie_template === 'string') {
      return t('presets.value.ownNaming', { template: value.movie_template })
    }
  }
  if (typeof value === 'string' && path === 'output.container') {
    return system.definitions?.containers?.[value]?.label
  }
  if (typeof value === 'string' && /(^|\.)encoder$/.test(path)) {
    const encoders = path.startsWith('video')
      ? system.definitions?.video_encoders
      : system.definitions?.audio_encoders
    return encoders?.[value]?.label
  }
  if (!isObject(value)) return undefined
  if (path === 'video.rate_control') return rateControl(value, encoder)
  if (path === 'dimensions.size') return size(value)
  return undefined
}

function wordsFor(encoder: string | null | undefined): Words {
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
    known: (path, value) => knownWords(path, value, encoder),
  }
}

const rows = computed(() => {
  // A quality before and after an encoder change is on each encoder's own scale.
  const encoderChange = props.changes.find((change) => change.path === 'video.encoder')
  const before = wordsFor((encoderChange?.preset_value as string | undefined) ?? props.encoder)
  const after = wordsFor((encoderChange?.value as string | undefined) ?? props.encoder)
  return props.changes.map((change, index) => ({
    key: `${change.path}:${index}`,
    kind: change.kind,
    label: pathWords(change.path, after),
    before: valueWords(change.preset_value, before, change.path),
    after: valueWords(change.value, after, change.path),
  }))
})
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
