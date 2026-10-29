<script setup lang="ts">
import { RotateCcw } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import vTooltip from 'primevue/tooltip'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NameResult, Schemas, ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'

import { type OverrideField, OVERRIDE_FIELDS } from './fields'
import { segments, type SpanTone, toneOf } from './spans'

type ParsedName = Schemas['ParsedName']
type NameCandidate = Schemas['NameCandidate']

/**
 * How a source's name was read: the chosen name source and why, each candidate with its
 * recognised parts coloured, and (when `editable`) the fields as inputs: an edit is a per-file
 * override of what the parser found.
 */
const props = defineProps<{
  result: NameResult
  editable?: boolean
  /** The job's `field_overrides`. */
  overrides?: Record<string, string>
  /** Issues of the overrides (`output.naming.field_overrides.<field>`). */
  issues?: ValidationIssue[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:overrides': [value: Record<string, string>]
  /** Typing in a field ended (blur). */
  commit: []
}>()

const { t } = useI18n()

function sourceLabel(kind: 'file' | 'folder'): string {
  return kind === 'file' ? t('naming.parsed.fileName') : t('naming.parsed.folderName')
}

function toneLabel(tone: SpanTone): string {
  switch (tone) {
    case 'title':
      return t('naming.tone.title')
    case 'episode':
      return t('naming.tone.episode')
    case 'subtitle':
      return t('naming.tone.subtitle')
    case 'year':
      return t('naming.tone.year')
    case 'resolution':
      return t('naming.tone.resolution')
    case 'source':
      return t('naming.tone.source')
    case 'edition':
      return t('naming.tone.edition')
    case 'group':
      return t('naming.tone.group')
    case 'other':
      return t('naming.tone.other')
  }
}

function fieldLabel(field: OverrideField): string {
  switch (field) {
    case 'name':
      return t('naming.field.name')
    case 'main_title':
      return t('naming.field.main_title')
    case 'sub_title':
      return t('naming.field.sub_title')
    case 'season':
      return t('naming.field.season')
    case 'episode':
      return t('naming.field.episode')
    case 'episode_code':
      return t('naming.field.episode_code')
    case 'year':
      return t('naming.field.year')
    case 'edition':
      return t('naming.field.edition')
    case 'source_type':
      return t('naming.field.source_type')
    case 'release_group':
      return t('naming.field.release_group')
  }
}

const candidates = computed(() =>
  (props.result.candidates ?? []).map((candidate) => ({
    candidate,
    chosen: candidate.kind === props.result.source,
    segments: segments(candidate.text, candidate.spans ?? []),
  })),
)

const legend = computed<SpanTone[]>(() => {
  const seen = new Set<SpanTone>()
  for (const candidate of props.result.candidates ?? []) {
    for (const span of candidate.spans ?? []) seen.add(toneOf(span.field))
  }
  return (
    [
      'title',
      'episode',
      'subtitle',
      'year',
      'resolution',
      'source',
      'edition',
      'group',
      'other',
    ] as SpanTone[]
  ).filter((tone) => seen.has(tone))
})

function shown(value: ParsedName[OverrideField] | undefined): string {
  return value === null || value === undefined ? '' : String(value)
}

/** What the parser found, before this file's overrides. */
function parsed(field: OverrideField): string {
  const chosen: NameCandidate | undefined = props.result.candidates?.find(
    (candidate) => candidate.kind === props.result.source,
  )
  return shown(chosen?.fields?.[field])
}

function valueOf(field: OverrideField): string {
  const override = props.overrides?.[field]
  return override ?? shown(props.result.fields?.[field])
}

function overridden(field: OverrideField): boolean {
  return props.overrides !== undefined && field in props.overrides
}

function edit(field: OverrideField, value: string | undefined): void {
  emit('update:overrides', { ...props.overrides, [field]: value ?? '' })
}

function reset(field: OverrideField): void {
  const next = { ...props.overrides }
  delete next[field]
  emit('update:overrides', next)
}

function issuesOf(field: OverrideField): ValidationIssue[] {
  return (props.issues ?? []).filter(
    (issue) => issue.path === `output.naming.field_overrides.${field}`,
  )
}
</script>

<template>
  <div class="parsed-name">
    <p class="parsed-name__source">
      <strong>{{ t('naming.parsed.source', { source: sourceLabel(result.source) }) }}</strong>
      <span v-if="result.season_pack" class="parsed-name__badge">{{
        t('naming.parsed.seasonPack')
      }}</span>
    </p>
    <p class="parsed-name__reason" data-testid="name-reason">{{ result.reason }}</p>
    <p v-if="(result.skipped_folders ?? []).length > 0" class="parsed-name__skipped">
      {{ t('naming.parsed.skipped', { folders: (result.skipped_folders ?? []).join(', ') }) }}
    </p>

    <ul class="parsed-name__candidates">
      <li
        v-for="entry in candidates"
        :key="entry.candidate.kind"
        class="parsed-name__candidate"
        :class="{ 'parsed-name__candidate--chosen': entry.chosen }"
        :data-kind="entry.candidate.kind"
      >
        <span class="parsed-name__kind">
          {{ sourceLabel(entry.candidate.kind) }}
          <span class="parsed-name__score">{{
            t('naming.parsed.score', { n: entry.candidate.score }, entry.candidate.score)
          }}</span>
          <span v-if="entry.chosen" class="parsed-name__badge">{{
            t('naming.parsed.chosen')
          }}</span>
        </span>
        <span class="parsed-name__text">
          <template v-for="(segment, index) in entry.segments" :key="index">
            <mark
              v-if="segment.span"
              v-tooltip.top="toneLabel(toneOf(segment.span.field))"
              class="parsed-name__span"
              :class="`parsed-name__span--${toneOf(segment.span.field)}`"
              :data-field="segment.span.field"
              >{{ segment.text
              }}<span class="rf-sr-only"> ({{ toneLabel(toneOf(segment.span.field)) }})</span></mark
            >
            <span v-else>{{ segment.text }}</span>
          </template>
        </span>
      </li>
    </ul>

    <ul
      v-if="legend.length > 0"
      class="parsed-name__legend"
      :aria-label="t('naming.parsed.legend')"
    >
      <li v-for="tone in legend" :key="tone">
        <span
          class="parsed-name__swatch"
          :class="`parsed-name__span--${tone}`"
          aria-hidden="true"
        />
        {{ toneLabel(tone) }}
      </li>
    </ul>

    <p v-if="editable" class="parsed-name__hint">{{ t('naming.parsed.overrideHint') }}</p>
    <div v-if="editable" class="parsed-name__fields">
      <Field
        v-for="field in OVERRIDE_FIELDS"
        :key="field"
        :label="fieldLabel(field)"
        :path="`output.naming.field_overrides.${field}`"
        :issues="issuesOf(field)"
        stacked
      >
        <template #default="{ id, invalid }">
          <div class="parsed-name__field">
            <InputText
              :id="id"
              :model-value="valueOf(field)"
              :invalid="invalid"
              :disabled="disabled"
              :data-field="field"
              :placeholder="overridden(field) ? t('naming.parsed.cleared') : undefined"
              :inputmode="
                field === 'season' || field === 'episode' || field === 'year'
                  ? 'numeric'
                  : undefined
              "
              fluid
              @update:model-value="edit(field, $event)"
              @blur="emit('commit')"
            />
            <Button
              v-if="overridden(field)"
              v-tooltip.top="t('naming.parsed.resetTo', { value: parsed(field) || '—' })"
              text
              rounded
              size="small"
              :disabled="disabled"
              :aria-label="t('naming.parsed.reset', { field: fieldLabel(field) })"
              :data-reset="field"
              @click="reset(field)"
            >
              <template #icon>
                <RotateCcw :size="16" aria-hidden="true" />
              </template>
            </Button>
          </div>
        </template>
      </Field>
    </div>
  </div>
</template>

<style scoped>
.parsed-name {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.parsed-name p {
  margin: 0;
}

.parsed-name__source {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.parsed-name__reason,
.parsed-name__skipped,
.parsed-name__hint {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.parsed-name__badge {
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-primary);
  border-radius: var(--rf-radius-pill);
  color: var(--rf-color-primary);
  font-size: var(--rf-font-size-xs);
}

.parsed-name__candidates {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.parsed-name__candidate {
  display: grid;
  gap: var(--rf-space-1);
  padding: var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
}

.parsed-name__candidate--chosen {
  border-color: var(--rf-color-primary);
}

.parsed-name__kind {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
  font-weight: var(--rf-font-weight-medium);
}

.parsed-name__score {
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-normal);
}

.parsed-name__text {
  font-family: var(--rf-font-mono);
  line-height: 1.9;
  overflow-wrap: anywhere;
}

.parsed-name__span {
  padding: 0.05rem 0.1rem;
  border-bottom: 2px solid var(--naming-tone);
  border-radius: 2px;
  background: color-mix(in srgb, var(--naming-tone) 18%, transparent);
  color: inherit;
}

.parsed-name__span--title {
  --naming-tone: var(--p-blue-500);
}

.parsed-name__span--episode {
  --naming-tone: var(--p-violet-500);
}

.parsed-name__span--subtitle {
  --naming-tone: var(--p-cyan-600);
}

.parsed-name__span--year {
  --naming-tone: var(--p-amber-600);
}

.parsed-name__span--resolution {
  --naming-tone: var(--p-green-600);
}

.parsed-name__span--source {
  --naming-tone: var(--p-teal-600);
}

.parsed-name__span--edition {
  --naming-tone: var(--p-pink-500);
}

.parsed-name__span--group {
  --naming-tone: var(--p-fuchsia-600);
}

.parsed-name__span--other {
  --naming-tone: var(--p-slate-500);
}

.parsed-name__legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1) var(--rf-space-3);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--rf-font-size-sm);
}

.parsed-name__legend li {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.parsed-name__swatch {
  display: inline-block;
  width: 0.9rem;
  height: 0.9rem;
  border: 2px solid var(--naming-tone);
  border-radius: 2px;
  background: color-mix(in srgb, var(--naming-tone) 30%, transparent);
}

.parsed-name__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--rf-space-3);
  padding-left: var(--rf-space-2);
}

.parsed-name__field {
  display: flex;
  align-items: center;
  gap: var(--rf-space-1);
}
</style>
