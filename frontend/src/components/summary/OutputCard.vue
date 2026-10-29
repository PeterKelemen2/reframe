<script setup lang="ts">
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, onScopeDispose, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { JsonPatchOp, Schemas } from '@/api/types'
import Card from '@/components/base/Card.vue'
import Field from '@/components/base/Field.vue'
import JobNamingEditor from '@/components/naming/JobNamingEditor.vue'
import { withExtension } from '@/components/naming/path'
import { previewNames } from '@/components/naming/preview'
import { latestRequest } from '@/editor/latest'
import { type PendingEdit, useEditorStore } from '@/stores/editor'
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

/** A container change on its way: the path it wrote, and the undo step it belongs to. */
let change: { key: string; container: Container; path: string } | null = null
let changes = 0

function extensionsOf(container: Container): string[] {
  return system.definitions?.containers?.[container]?.extensions ?? []
}

const extensionRequest = latestRequest<{ extension: string }>({
  async send(signal) {
    const job = editor.job
    const target = editor.target
    if (job === null || target?.kind !== 'job') throw new Error('OutputCard: no job is open')
    const container = job.output?.container ?? 'mkv'
    const [answer] = await previewNames({ source_ids: [target.sourceId], job, container }, signal)
    if (answer === undefined) throw new Error('OutputCard: no name for the source')
    return { extension: answer.extension }
  },
  done({ extension }) {
    const job = editor.job
    // Only over the path the change wrote: an undo or another edit since then wins.
    if (
      change !== null &&
      job?.output?.container === change.container &&
      job.output.path === change.path
    ) {
      const path = withExtension(change.path, extension)
      if (path !== change.path) {
        editor.patch([{ op: 'add', path: '/output/path', value: path }], { coalesce: change.key })
      }
    }
    change = null
    editor.endEdit(extensionEdit)
  },
  failed() {
    // The container's first extension stays: a valid one, though maybe not the naming's.
    change = null
    editor.endEdit(extensionEdit)
  },
})
const extensionEdit: PendingEdit = reactive({
  flush: () => extensionRequest.flush(),
  failure: null,
})

function dropChange(): void {
  extensionRequest.cancel()
  change = null
  editor.endEdit(extensionEdit)
}
watch(() => editor.session, dropChange)
onScopeDispose(dropChange)

/**
 * The container and the path's extension in one undo step. The container's first extension
 * goes in at once; where the container has more than one (MP4: `.mp4`, `.m4v`), the naming's
 * choice follows in the same step when the server has named the job.
 */
function setContainer(value: Container | null): void {
  const job = editor.job
  if (value === null || job === null || value === job.output?.container) return
  const key = `output.container#${++changes}`
  const ops: JsonPatchOp[] = [{ op: 'add', path: '/output/container', value }]
  const path = job.output?.path
  const extensions = extensionsOf(value)
  const next = path ? withExtension(path, extensions[0] ?? value) : null
  if (next !== null && next !== path) ops.push({ op: 'add', path: '/output/path', value: next })
  dropChange()
  editor.patch(ops, { coalesce: key })
  if (next !== null && extensions.length !== 1) {
    change = { key, container: value, path: next }
    editor.beginEdit(extensionEdit)
    extensionRequest.schedule(0)
  }
}

function setFlag(flag: OutputFlag, value: boolean): void {
  editor.set(`/output/${flag}`, value)
}
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
</style>
