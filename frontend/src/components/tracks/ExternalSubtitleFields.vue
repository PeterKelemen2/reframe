<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Button from 'primevue/button'
import Select from 'primevue/select'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ExternalSubtitle, Fix, ValidationIssue } from '@/api/types'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import Field from '@/components/base/Field.vue'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

import { inspect, inspected, useSubtitleFormatName } from './external'
import { CHARSETS } from './metadata'

/** An external subtitle file's format, events and encoding, and the fields that set its offset. */
const props = defineProps<{
  index: number
  external: ExternalSubtitle
  disabled?: boolean
}>()

const { t } = useI18n()
const editor = useEditorStore()
const validation = useValidationStore()
const severityLabel = useSeverityLabel()
const formatName = useSubtitleFormatName()

// Select shows its placeholder for a `null` value, so "as detected" is a named value.
const AUTO = 'auto'

const path = computed(() => `subtitles[${props.index}].source`)
const pointer = computed(() => `/subtitles/${props.index}/source`)

/** The file is read again when the row has no answer for it (after a reload or an edit-back). */
watch(
  () => props.external.path,
  (file) => {
    if (inspected(file) === undefined) void inspect(file, { quiet: true })
  },
  { immediate: true },
)

const info = computed(() => inspected(props.external.path))
const bitmap = computed(
  () => info.value?.bitmap ?? props.external.path.toLowerCase().endsWith('.sup'),
)

const described = computed(() => {
  const found = info.value
  if (found === undefined) return t('tracks.external.inspecting')
  if (found === null) return t('tracks.external.unreadable')
  const format = formatName(found.format)
  let events: string
  if (found.events === null || found.events === undefined) {
    events = t('tracks.external.eventsUnknown')
  } else if (found.bitmap) {
    events = t('tracks.external.displaySets', { count: found.events }, found.events)
  } else {
    events = t('tracks.external.events', { count: found.events }, found.events)
  }
  return found.charset
    ? t('tracks.external.describedCharset', { format, events, charset: found.charset })
    : t('tracks.external.described', { format, events })
})

/** The inspection's warnings about the file itself (another format than its name, no events). */
const fileIssues = computed<ValidationIssue[]>(
  () => info.value?.issues?.filter((issue) => issue.path !== 'charset') ?? [],
)

/**
 * The encoding's issues: the validation's, or else the inspection's while the track names no
 * encoding. Both say the same about the file, so never both.
 */
const charsetIssues = computed<ValidationIssue[]>(() => {
  const validated = validation.issuesFor(`${path.value}.charset`)
  if (validated.length > 0) return validated
  if (props.external.charset) return []
  return (info.value?.issues ?? []).filter((issue) => issue.path === 'charset')
})

const charsetFixes = computed<Fix[]>(() => {
  const seen = new Set<string>()
  return charsetIssues.value
    .flatMap((issue) => issue.fixes ?? [])
    .filter((fix) => !seen.has(fix.label) && seen.add(fix.label))
})
const applying = ref(false)

async function applyFix(fix: Fix): Promise<void> {
  if (applying.value) return
  applying.value = true
  try {
    await editor.applyFix(fix)
  } finally {
    applying.value = false
  }
}

const charsetOptions = computed(() => {
  const detected = info.value?.charset
  const auto = detected
    ? t('tracks.external.charsetDetected', { charset: detected })
    : t('tracks.external.charsetMissing')
  const current = props.external.charset
  const names = current && !CHARSETS.includes(current) ? [current, ...CHARSETS] : CHARSETS
  return [{ value: AUTO, label: auto }, ...names.map((name) => ({ value: name, label: name }))]
})

function onCharset(value: string | null): void {
  const typed = value?.trim() ?? ''
  const charset = typed === '' || typed === AUTO ? null : typed
  editor.set(`${pointer.value}/charset`, charset, { coalesce: `${path.value}.charset` })
}

function onOffset(value: number | null): void {
  editor.set(`${pointer.value}/offset_ms`, Math.round(value ?? 0), {
    coalesce: `${path.value}.offset_ms`,
  })
}
</script>

<template>
  <div class="external-fields" data-role="external">
    <p class="external-fields__info" data-role="file-info">{{ described }}</p>
    <ul v-if="fileIssues.length > 0" class="external-fields__issues">
      <li
        v-for="(issue, at) in fileIssues"
        :key="`${issue.code}:${at}`"
        class="external-fields__issue"
        :data-code="issue.code"
      >
        <component :is="SEVERITY_ICON[issue.severity]" :size="14" aria-hidden="true" />
        <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
        <span>{{ issue.message }}</span>
      </li>
    </ul>
    <div class="external-fields__row">
      <Field
        :label="t('tracks.external.offset')"
        :path="`${path}.offset_ms`"
        :help="t('tracks.external.offsetHelp')"
        stacked
      >
        <template #default="{ id, invalid }">
          <InputNumber
            :input-id="id"
            class="external-fields__number"
            :model-value="external.offset_ms ?? 0"
            :step="100"
            :min-fraction-digits="0"
            :max-fraction-digits="0"
            :suffix="t('tracks.external.offsetSuffix')"
            show-buttons
            :disabled="disabled"
            :invalid="invalid"
            data-role="offset"
            @update:model-value="onOffset"
            @blur="editor.endCoalescing()"
          />
        </template>
      </Field>
      <div v-if="!bitmap" class="external-fields__charset-field">
        <Field
          :label="t('tracks.external.charset')"
          :path="`${path}.charset`"
          :help="t('tracks.external.charsetHelp')"
          :issues="charsetIssues"
          stacked
        >
          <template #default="{ id, labelId, invalid }">
            <Select
              :input-id="id"
              :ariaLabelledby="labelId"
              class="external-fields__charset"
              :model-value="external.charset ?? AUTO"
              :options="charsetOptions"
              option-label="label"
              option-value="value"
              editable
              :invalid="invalid"
              :disabled="disabled"
              data-role="charset"
              @update:model-value="onCharset"
              @blur="editor.endCoalescing()"
            />
          </template>
        </Field>
        <div
          v-if="charsetFixes.length > 0"
          class="external-fields__fixes"
          data-role="charset-fixes"
        >
          <Button
            v-for="fix in charsetFixes"
            :key="fix.label"
            size="small"
            severity="secondary"
            outlined
            :label="fix.label"
            :disabled="applying || disabled"
            @click="applyFix(fix)"
          />
        </div>
      </div>
      <p v-else class="external-fields__note" data-note="bitmap">
        {{ t('tracks.external.charsetBitmap') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.external-fields {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

/* Level with the offset's input, below its label. */
.external-fields__row > .external-fields__note {
  padding-top: 2.4rem;
}

.external-fields__info,
.external-fields__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.external-fields__issues {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--rf-font-size-sm);
}

.external-fields__issue {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-1);
  color: var(--p-status-warn-color);
}

.external-fields__issue svg {
  flex: none;
  margin-top: 0.15em;
}

.external-fields__row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-3);
  align-items: flex-start;
}

.external-fields__row > * {
  flex: 1 1 12rem;
  min-width: 0;
}

/* A label with a help button is taller: every label gets its height, so the controls line up. */
.external-fields__row :deep(.rf-field__label) {
  min-height: 1.75rem;
}

.external-fields__fixes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
  margin-top: var(--rf-space-2);
}

.external-fields__number,
.external-fields__charset {
  width: 100%;
}

.external-fields__number :deep(input) {
  width: 100%;
  min-width: 0;
}
</style>
