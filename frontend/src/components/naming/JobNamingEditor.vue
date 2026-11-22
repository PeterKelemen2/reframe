<script setup lang="ts">
import { FolderOpen, RotateCcw } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed, onScopeDispose, reactive, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { JobNaming, JobSettings, JsonPatchOp, NameResult } from '@/api/types'
import Field from '@/components/base/Field.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import { latestRequest } from '@/editor/latest'
import { sameJson } from '@/editor/patch'
import { platform } from '@/platform'
import { type PendingEdit, useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

import Disclosure from './Disclosure.vue'
import NamingIssues from './NamingIssues.vue'
import ParsedNamePanel from './ParsedNamePanel.vue'
import { folderOf, joinPath, nextOutputPath } from './path'
import { failureText, isTemplateIssue, PREVIEW_DEBOUNCE, previewNames } from './preview'
import TemplateField from './TemplateField.vue'
import TemplateFixes from './TemplateFixes.vue'
import VariableChips from './VariableChips.vue'

/**
 * The editor's job's output name (the Summary tab's Output card): the template or a manual
 * name, the name source, the parsed-name panel with per-file field overrides, and the output
 * folder. An edit waits here for its preview; then the naming and the output path go into the
 * job in one patch. Until then it is a pending edit of the editor store, which an add to the
 * queue waits for. An edit on its way when the editor unmounts still goes into the job.
 */
const props = defineProps<{
  disabled?: boolean
  /** Variable chips and the parsed name start folded (a narrow place). */
  compact?: boolean
}>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const toasts = useToastStore()

const EMPTY: JobNaming = {
  mode: 'template',
  manual_name: null,
  template: null,
  name_source: null,
  field_overrides: {},
}

/** JSON with sorted keys: a naming read from the server and one built here compare equal. */
function stable(value: unknown): string {
  return JSON.stringify(value, (_key, inner: unknown) =>
    inner !== null && typeof inner === 'object' && !Array.isArray(inner)
      ? Object.fromEntries(Object.entries(inner).toSorted(([a], [b]) => a.localeCompare(b)))
      : inner,
  )
}

function namingOf(job: JobSettings | null): JobNaming {
  return { ...EMPTY, ...structuredClone(job?.output?.naming ?? EMPTY) }
}

function sameNaming(a: JobNaming | undefined, b: JobNaming | undefined): boolean {
  return stable({ ...EMPTY, ...a }) === stable({ ...EMPTY, ...b })
}

const templateField = useTemplateRef<InstanceType<typeof TemplateField>>('templateField')
const chipsOpen = ref(!props.compact)
const parsedOpen = ref(!props.compact)

/** The naming being edited; it reaches the job with the preview's answer. */
const local = shallowRef<JobNaming>(namingOf(editor.job))
/** The preview of the job with `local`. */
const result = shallowRef<NameResult | null>(null)
/** The preview of the job as it is: its relative name tells the job's folder from its path. */
const applied = shallowRef<{ job: JobSettings; result: NameResult } | null>(null)
const pending = ref(false)
const failure = ref<string | null>(null)

/** The job this editor's own patch made: not a change from elsewhere. */
let ownJob: JobSettings | null = null
/** The coalescing key of the last edit (typing in one field is one undo step). */
let editKey: string | undefined
/** A text field lost the focus while its edit was on its way: end the step after it lands. */
let endAfterCommit = false
/** Unmounted with an edit on its way: the session it belongs to. */
let detached: number | null = null

/** The name the job's path was made with (it tells the job's folder from its path). */
function previousName(job: JobSettings): string | null | undefined {
  return (
    applied.value?.result.relative_path ??
    (editor.draft?.job === job ? editor.draft.naming?.relative_path : null)
  )
}

function targetSource(): string | null {
  return editor.target?.sourceId ?? null
}

const inGroup = computed(() => editor.target?.kind === 'group')
/** The edits go into the group's template, which cannot hold the per-file fields. */
const groupScope = computed(
  () => editor.target?.kind === 'group' && editor.target.scope === 'group',
)

/** The fields show a naming that the job does not have yet. */
function isUnapplied(): boolean {
  return editor.job !== null && !sameNaming(local.value, editor.job.output?.naming)
}

function flushEdit(): void {
  if (pending.value) runner.flush()
  else schedule(0)
}

const pendingEdit: PendingEdit = reactive({
  flush: flushEdit,
  get failure() {
    return failure.value
  },
})
watch(
  isUnapplied,
  (on) => {
    if (on) editor.beginEdit(pendingEdit)
    else editor.endEdit(pendingEdit)
  },
  { immediate: true, flush: 'sync' },
)

function finishGesture(): void {
  if (!endAfterCommit) return
  endAfterCommit = false
  editor.endCoalescing()
}

/**
 * In a group the server names each file, so the path stays; only the changed naming members
 * are patched, so that a file's override holds only what was edited for it.
 */
function groupOps(base: JobSettings, naming: JobNaming): JsonPatchOp[] {
  const before: JobNaming = { ...EMPTY, ...base.output?.naming }
  return (Object.keys(naming) as (keyof JobNaming)[])
    .filter((key) => !sameJson(naming[key], before[key]))
    .map((key) => ({ op: 'add', path: `/output/naming/${key}`, value: naming[key] }) as JsonPatchOp)
}

function commit(base: JobSettings, naming: JobNaming, path: string | null): void {
  let ops: JsonPatchOp[] = [{ op: 'add', path: '/output/naming', value: naming }]
  if (inGroup.value) ops = groupOps(base, naming)
  else if (path !== (base.output?.path ?? null)) {
    ops.push({ op: 'add', path: '/output/path', value: path })
  }
  editor.patch(ops, editKey === undefined ? undefined : { coalesce: editKey })
  ownJob = editor.job
}

const runner = latestRequest<{ base: JobSettings; naming: JobNaming; answer: NameResult }>({
  async send(signal) {
    const base = editor.job
    const id = targetSource()
    if (base === null || id === null) throw new Error('JobNamingEditor: no job is open')
    const naming = local.value
    const job = { ...base, output: { ...base.output, naming } } as JobSettings
    const [answer] = await previewNames(
      { source_ids: [id], job, container: base.output?.container ?? 'mkv' },
      signal,
    )
    if (answer === undefined) throw new Error('JobNamingEditor: no name for the source')
    return { base, naming, answer }
  },
  done({ base, naming, answer }) {
    if (detached !== null && detached !== editor.session) {
      editor.endEdit(pendingEdit)
      return
    }
    // The job changed after the request went out (a change the job watcher has not seen yet,
    // or one made after the editor unmounted): name the job as it is now.
    if (editor.job !== base) {
      runner.schedule(0)
      return
    }
    pending.value = false
    failure.value = null
    result.value = answer
    if (!sameNaming(naming, base.output?.naming)) {
      commit(base, naming, nextOutputPath(base.output?.path, previousName(base), answer))
    }
    applied.value = editor.job === null ? null : { job: editor.job, result: answer }
    if (detached !== null) editor.endEdit(pendingEdit)
    finishGesture()
  },
  failed(error) {
    pending.value = false
    // The edit stays out of the job: the job keeps a naming and a path that belong together.
    failure.value = failureText(error) ?? t('naming.preview.failed')
    if (detached !== null) {
      editor.endEdit(pendingEdit)
      if (detached === editor.session) {
        toasts.push({
          severity: 'warn',
          summary: t('naming.job.notApplied'),
          detail: failure.value,
          life: 10_000,
        })
      }
    }
    finishGesture()
  },
})
onScopeDispose(() => {
  if (isUnapplied() && failure.value === null) {
    detached = editor.session
    flushEdit()
    return
  }
  runner.cancel()
  editor.endEdit(pendingEdit)
})

function schedule(delay: number): void {
  if (editor.job === null || targetSource() === null) {
    runner.cancel()
    pending.value = false
    return
  }
  pending.value = true
  failure.value = null
  runner.schedule(delay)
}

watch(
  () => editor.session,
  () => {
    applied.value = null
    result.value = null
    failure.value = null
    ownJob = null
  },
)

watch(
  () => editor.job,
  (job, previous) => {
    if (job === null) {
      runner.cancel()
      pending.value = false
      result.value = null
      applied.value = null
      local.value = namingOf(null)
      return
    }
    if (job === ownJob) return
    const fresh = applied.value === null
    if (fresh || !sameNaming(job.output?.naming, previous?.output?.naming)) {
      local.value = namingOf(job)
    }
    const draft = editor.draft
    if (draft?.job === job && draft.naming && sameNaming(local.value, job.output?.naming)) {
      runner.cancel()
      pending.value = false
      result.value = draft.naming
      applied.value = { job, result: draft.naming }
      return
    }
    schedule(fresh ? 0 : PREVIEW_DEBOUNCE)
  },
  { immediate: true },
)

function edit(change: Partial<JobNaming>, key?: string): void {
  local.value = { ...local.value, ...change }
  editKey = key
  schedule(PREVIEW_DEBOUNCE)
}

/**
 * A text field lost the focus: its edit is previewed at once (an add to the queue may come
 * next), and the undo step of its typing ends when it lands.
 */
function onBlur(): void {
  if (!isUnapplied()) {
    editor.endCoalescing()
    return
  }
  endAfterCommit = true
  flushEdit()
}

/** Without a template of its own, the job uses the naming options' (the preset's, else the settings'). */
const templateText = computed(() => {
  if (local.value.template !== null && local.value.template !== undefined) {
    return local.value.template
  }
  const named = applied.value?.result ?? result.value
  return named === null || named.template_kind === 'manual' ? '' : named.template
})

const modes = computed(() => [
  { value: 'template', label: t('naming.job.modeTemplate') },
  { value: 'manual', label: t('naming.job.modeManual') },
])
/** The Select shows no option for `null`, so "as the naming options say" has a value of its own. */
const FROM_OPTIONS = 'options'
/** A file of a group without a name source of its own is named with the group's. */
const shownNameSource = computed(
  () =>
    local.value.name_source ??
    (inGroup.value ? editor.currentTemplate?.naming?.name_source : null) ??
    FROM_OPTIONS,
)
/**
 * A group's template keeps its naming when the job has none (`null`), so in scope `group` the
 * naming options are offered only while the group has no name source of its own.
 */
const nameSources = computed(() => [
  ...(groupScope.value && shownNameSource.value !== FROM_OPTIONS
    ? []
    : [{ value: FROM_OPTIONS, label: t('naming.job.sourceOptions') }]),
  { value: 'auto', label: t('naming.source.auto') },
  { value: 'file', label: t('naming.source.file') },
  { value: 'folder', label: t('naming.source.folder') },
])

function stemOf(relative: string): string {
  const name = relative.split('/').at(-1) ?? relative
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

function setMode(mode: JobNaming['mode']): void {
  const named = result.value
  const manual =
    mode === 'manual' && !local.value.manual_name && named !== null
      ? stemOf(named.relative_path)
      : local.value.manual_name
  edit({ mode, manual_name: manual ?? null })
}

function useTemplate(template: string): void {
  edit({ template })
}

function insertVariable(name: string): void {
  if (local.value.mode !== 'template') return
  templateField.value?.insert(`{${name}}`)
}

const issues = computed(() => result.value?.issues ?? [])
const templateIssues = computed(() => issues.value.filter(isTemplateIssue))
const manualIssues = computed(() =>
  issues.value.filter((issue) => issue.path === 'output.naming.manual_name'),
)
const overrideIssues = computed(() =>
  issues.value.filter((issue) => issue.path.startsWith('output.naming.field_overrides')),
)
const otherIssues = computed(() =>
  issues.value.filter(
    (issue) =>
      !isTemplateIssue(issue) &&
      issue.path !== 'output.naming.manual_name' &&
      !issue.path.startsWith('output.naming.field_overrides'),
  ),
)

const outputPath = computed(() => editor.job?.output?.path ?? null)
const folder = computed(() =>
  folderOf(outputPath.value, applied.value?.result.relative_path ?? null),
)
/** The folder of the naming options: where the job goes when no folder was chosen for it. */
const defaultFolder = computed(() => {
  const named = applied.value?.result ?? result.value
  return named?.path ? folderOf(named.path, named.relative_path) : null
})
const ownFolder = computed(
  () =>
    folder.value !== null && defaultFolder.value !== null && folder.value !== defaultFolder.value,
)
/** The path the job's naming gives now, when the job's path is another (the job changed since). */
const expectedPath = computed(() => {
  const now = applied.value
  const job = editor.job
  if (now === null || job === null || now.job !== job || pending.value || inGroup.value) return null
  const expected = nextOutputPath(job.output?.path, now.result.relative_path, now.result)
  if (expected === null || expected === (job.output?.path ?? null)) return null
  return expected === job.source.path ? null : expected
})

function setPath(path: string): void {
  editor.set('/output/path', path)
}

async function chooseFolder(): Promise<void> {
  const named = applied.value?.result ?? result.value
  if (named === null) return
  let picked: string | null
  try {
    picked = await platform.pickFolder({ title: t('naming.folder.pickTitle') })
  } catch {
    toasts.push({ severity: 'warn', summary: t('naming.folder.pickFailed'), life: 8000 })
    return
  }
  if (picked !== null) setPath(joinPath(picked, named.relative_path))
}

function useDefaultFolder(): void {
  const path = applied.value?.result.path
  if (path) setPath(path)
}
</script>

<template>
  <div class="job-naming-editor">
    <p v-if="editor.job === null" class="job-naming__empty">{{ t('naming.job.noJob') }}</p>
    <template v-else>
      <p v-if="groupScope" class="job-naming__per-file" data-role="per-file">
        {{ t('naming.job.perFileInGroup') }}
      </p>
      <Field v-else :label="t('naming.job.mode')" path="output.naming.mode" stacked>
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="local.mode"
            :options="modes"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="disabled"
            data-option="mode"
            @update:model-value="setMode"
          />
        </template>
      </Field>

      <Field
        v-if="local.mode === 'template'"
        :label="t('naming.job.template')"
        path="output.naming.template"
        :issues="templateIssues"
        stacked
      >
        <template #default="{ id, invalid }">
          <div class="job-naming__row">
            <TemplateField
              :id="id"
              ref="templateField"
              class="job-naming__grow"
              :model-value="templateText"
              :variables="system.namingVariables"
              :invalid="invalid"
              :disabled="disabled"
              @update:model-value="edit({ template: $event }, 'output.naming.template')"
              @blur="onBlur"
            />
            <Button
              v-if="local.template !== null && !groupScope"
              :label="t('naming.job.resetTemplate')"
              severity="secondary"
              text
              size="small"
              :disabled="disabled"
              data-action="reset-template"
              @click="edit({ template: null })"
            >
              <template #icon>
                <RotateCcw :size="16" aria-hidden="true" />
              </template>
            </Button>
          </div>
          <TemplateFixes :issues="templateIssues" :disabled="disabled" @use="useTemplate" />
        </template>
      </Field>
      <Field
        v-else
        :label="t('naming.job.manualName')"
        :help="t('naming.job.manualHelp')"
        path="output.naming.manual_name"
        :issues="manualIssues"
        stacked
      >
        <template #default="{ id, invalid }">
          <div class="job-naming__row">
            <InputText
              :id="id"
              class="job-naming__grow"
              :model-value="local.manual_name ?? ''"
              :invalid="invalid"
              :disabled="disabled"
              fluid
              data-option="manual_name"
              @update:model-value="edit({ manual_name: $event ?? '' }, 'output.naming.manual_name')"
              @blur="onBlur"
            />
            <Button
              :label="t('naming.job.backToTemplate')"
              severity="secondary"
              text
              size="small"
              :disabled="disabled"
              data-action="back-to-template"
              @click="setMode('template')"
            >
              <template #icon>
                <RotateCcw :size="16" aria-hidden="true" />
              </template>
            </Button>
          </div>
        </template>
      </Field>

      <Disclosure
        v-if="local.mode === 'template'"
        v-model:open="chipsOpen"
        :title="t('naming.chips.title')"
      >
        <VariableChips
          :variables="system.namingVariables"
          :values="result?.variables ?? null"
          :disabled="disabled"
          @insert="insertVariable"
        />
      </Disclosure>

      <Field :label="t('naming.job.nameSource')" path="output.naming.name_source" stacked>
        <template #default="{ id, labelId }">
          <Select
            :label-id="id"
            :ariaLabelledby="labelId"
            :model-value="shownNameSource"
            :options="nameSources"
            option-label="label"
            option-value="value"
            :disabled="disabled"
            data-option="name_source"
            @update:model-value="edit({ name_source: $event === FROM_OPTIONS ? null : $event })"
          />
        </template>
      </Field>
      <p v-if="groupScope" class="job-naming__per-file" data-role="group-naming">
        {{ t('naming.job.groupNaming') }}
      </p>

      <section class="job-naming__output" :aria-label="t('naming.preview.title')">
        <div class="job-naming__head">
          <h4>{{ t('naming.preview.title') }}</h4>
          <span class="job-naming__status" aria-live="polite">{{
            pending ? t('naming.preview.updating') : ''
          }}</span>
        </div>
        <p v-if="failure !== null" class="job-naming__failure" role="alert">
          {{ t('naming.preview.failedWith', { reason: failure }) }}
        </p>
        <code v-if="result" class="job-naming__name" data-testid="naming-result">{{
          result.relative_path
        }}</code>
        <dl class="rf-kv-list job-naming__paths">
          <KeyValue :label="t('naming.job.folder')">
            <span class="job-naming__folder" data-testid="job-folder">{{ folder ?? '—' }}</span
            >{{ ' '
            }}<span class="job-naming__origin">{{
              ownFolder ? t('naming.job.folderOwn') : t('naming.job.folderDefault')
            }}</span>
          </KeyValue>
          <KeyValue :label="t('naming.job.path')">
            <code class="job-naming__path" data-testid="job-path">{{ outputPath ?? '—' }}</code>
          </KeyValue>
        </dl>
        <div v-if="!groupScope" class="job-naming__actions">
          <Button
            :label="t('naming.job.chooseFolder')"
            severity="secondary"
            outlined
            size="small"
            :disabled="disabled || result === null"
            data-action="choose-folder"
            @click="chooseFolder"
          >
            <template #icon>
              <FolderOpen :size="16" aria-hidden="true" />
            </template>
          </Button>
          <Button
            v-if="ownFolder"
            :label="t('naming.job.useDefaultFolder')"
            severity="secondary"
            text
            size="small"
            :disabled="disabled"
            data-action="default-folder"
            @click="useDefaultFolder"
          />
        </div>
        <div v-if="expectedPath !== null" class="job-naming__stale" data-testid="stale-path">
          <span>{{ t('naming.job.stale', { path: expectedPath }) }}</span>
          <Button
            :label="t('naming.job.updatePath')"
            size="small"
            severity="secondary"
            outlined
            :disabled="disabled"
            data-action="update-path"
            @click="setPath(expectedPath)"
          />
        </div>
        <NamingIssues :issues="otherIssues" />
        <ul v-if="(result?.notes ?? []).length > 0" class="job-naming__notes">
          <li v-for="(note, index) in result?.notes ?? []" :key="index">{{ note }}</li>
        </ul>
      </section>

      <Disclosure v-if="result" v-model:open="parsedOpen" :title="t('naming.parsed.heading')">
        <ParsedNamePanel
          :result="result"
          :editable="!groupScope"
          :overrides="local.field_overrides ?? {}"
          :issues="overrideIssues"
          :disabled="disabled"
          @update:overrides="edit({ field_overrides: $event }, 'output.naming.field_overrides')"
          @commit="onBlur"
        />
      </Disclosure>
    </template>
  </div>
</template>

<style scoped>
.job-naming-editor {
  display: grid;
  gap: var(--rf-space-4);
  min-width: 0;
}

.job-naming__empty,
.job-naming__per-file {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.job-naming__per-file {
  font-size: var(--rf-font-size-sm);
}

.job-naming__row {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.job-naming__grow {
  flex: 1;
  min-width: 0;
}

.job-naming__output {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.job-naming__head {
  display: flex;
  align-items: baseline;
  gap: var(--rf-space-3);
}

.job-naming__head h4 {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.job-naming__status {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.job-naming__failure {
  margin: 0;
  color: var(--p-status-error-color);
}

.job-naming__name {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-md);
  font-weight: var(--rf-font-weight-bold);
  overflow-wrap: anywhere;
}

.job-naming__paths {
  margin: 0;
}

.job-naming__origin {
  margin-left: var(--rf-space-2);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.job-naming__path {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
}

.job-naming__actions,
.job-naming__stale {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.job-naming__stale {
  padding: var(--rf-space-2);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
  color: var(--p-status-warn-color);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.job-naming__notes {
  margin: 0;
  padding-left: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
