<script setup lang="ts">
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Schemas } from '@/api/types'
import Card from '@/components/base/Card.vue'
import Field from '@/components/base/Field.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import JobNamingEditor from '@/components/naming/JobNamingEditor.vue'
import { fileName } from '@/components/shell/format'
import { sameJson } from '@/editor/patch'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

type Container = Schemas['OutputSettings']['container']
type OutputFlag = 'web_optimized' | 'align_av_start' | 'passthru_metadata'

const CONTAINERS: Container[] = ['mkv', 'mp4', 'webm']

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()

const output = computed(() => editor.job?.output ?? null)

const containerOptions = computed(() =>
  CONTAINERS.map((id) => ({
    value: id,
    label: system.definitions?.containers?.[id]?.label ?? id.toUpperCase(),
  })),
)

/** *Web optimized* is an option of the containers whose muxer has it (MP4's faststart). */
const webOptimizedApplies = computed(() => {
  const container = output.value?.container
  if (container === undefined) return false
  const flags = system.definitions?.containers?.[container]?.format_flags
  return flags === undefined ? container === 'mp4' : Object.hasOwn(flags, 'web_optimized')
})

function setContainer(value: Container | null): void {
  if (value !== null) editor.set('/output/container', value)
}

function setFlag(flag: OutputFlag, value: boolean): void {
  editor.set(`/output/${flag}`, value)
}

const path = computed(() => output.value?.path ?? null)
const name = computed(() => (path.value === null ? null : fileName(path.value)))
const folder = computed(() => {
  if (path.value === null || name.value === null) return null
  return path.value.slice(0, path.value.length - name.value.length).replace(/[/\\]$/, '') || null
})

/**
 * The name source: the one the draft chose (with its reason) while the job's naming is the
 * drafted one, else the job's setting.
 */
const nameSource = computed<{ text: string; reason: string | null } | null>(() => {
  const job = editor.job
  if (job === null) return null
  const naming = job.output?.naming
  if (naming?.mode === 'manual') return { text: t('summary.output.nameManual'), reason: null }
  const draft = editor.draft
  if (
    draft !== null &&
    sameJson(draft.job.output?.naming, naming) &&
    draft.job.output?.container === job.output?.container
  ) {
    const chosen =
      draft.naming.source === 'folder'
        ? t('summary.output.nameFolder')
        : t('summary.output.nameFile')
    return { text: chosen, reason: draft.naming.reason }
  }
  switch (naming?.name_source ?? 'auto') {
    case 'file':
      return { text: t('summary.output.nameFile'), reason: null }
    case 'folder':
      return { text: t('summary.output.nameFolder'), reason: null }
    default:
      return { text: t('summary.output.nameAuto'), reason: null }
  }
})
</script>

<template>
  <Card
    class="summary-card summary-card--wide summary-output"
    :title="t('summary.output.title')"
    data-card="output"
  >
    <div v-if="output" class="summary-output__body">
      <div class="summary-output__options">
        <Field :label="t('summary.output.container')" path="output.container">
          <template #default="{ labelId }">
            <SelectButton
              :ariaLabelledby="labelId"
              :model-value="output.container"
              :options="containerOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              data-field="container"
              @update:model-value="setContainer"
            />
          </template>
        </Field>
        <Field
          v-if="webOptimizedApplies"
          :label="t('summary.output.webOptimized')"
          :help="t('summary.output.webOptimizedHelp')"
          path="output.web_optimized"
        >
          <template #default="{ id }">
            <ToggleSwitch
              :input-id="id"
              :model-value="output.web_optimized"
              data-field="web-optimized"
              @update:model-value="setFlag('web_optimized', $event)"
            />
          </template>
        </Field>
        <Field
          :label="t('summary.output.alignAvStart')"
          :help="t('summary.output.alignAvStartHelp')"
          path="output.align_av_start"
        >
          <template #default="{ id }">
            <ToggleSwitch
              :input-id="id"
              :model-value="output.align_av_start"
              data-field="align-av-start"
              @update:model-value="setFlag('align_av_start', $event)"
            />
          </template>
        </Field>
        <Field
          :label="t('summary.output.passthruMetadata')"
          :help="t('summary.output.passthruMetadataHelp')"
          path="output.passthru_metadata"
        >
          <template #default="{ id }">
            <ToggleSwitch
              :input-id="id"
              :model-value="output.passthru_metadata"
              data-field="passthru-metadata"
              @update:model-value="setFlag('passthru_metadata', $event)"
            />
          </template>
        </Field>
      </div>
      <dl class="rf-kv-list summary-output__path">
        <KeyValue :label="t('summary.output.folder')">
          <span data-field="folder">{{ folder ?? t('summary.output.noPath') }}</span>
        </KeyValue>
        <KeyValue :label="t('summary.output.fileName')">
          <span class="summary-output__name" data-field="file-name">
            {{ name ?? t('summary.output.noPath') }}
          </span>
        </KeyValue>
        <KeyValue v-if="nameSource" :label="t('summary.output.nameSource')">
          <span data-field="name-source">
            <span>{{ nameSource.text }}</span>
            <span v-if="nameSource.reason" class="summary-card__note">
              {{ nameSource.reason }}
            </span>
          </span>
        </KeyValue>
      </dl>
      <JobNamingEditor />
    </div>
  </Card>
</template>

<style scoped>
.summary-output__body,
.summary-output__options {
  display: grid;
  gap: var(--rf-space-3);
}

.summary-output__name {
  font-weight: var(--rf-font-weight-medium);
}

[data-field='name-source'] {
  display: grid;
  gap: var(--rf-space-1);
}
</style>
