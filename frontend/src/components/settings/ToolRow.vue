<script setup lang="ts">
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import { computed, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import { formatList } from '@/components/shell/format'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import { familyOf, resetOps, setByEnvironment, type ToolInfo, toolTone } from './tools'
import { useBundledTools } from './useBundledTools'
import { readPointer, useSetting } from './useSetting'

const props = defineProps<{
  tool: ToolInfo
  /** `web`: the server refuses a tool path from a client; removing one is allowed. */
  mode: 'web' | 'desktop'
  /** The server's settings are read-only. */
  locked: boolean
}>()

const { t, locale } = useI18n()
const settings = useSettingsStore()
const system = useSystemStore()

const pointer = `/tools/${props.tool.name}`
const override = useSetting<string | null>(pointer)

const byEnvironment = computed(() => setByEnvironment(props.tool))
const editable = computed(() => props.mode === 'desktop' && !byEnvironment.value && !props.locked)
/** The path the settings hold now (not a refused one). */
const saved = computed(() => {
  const value = readPointer(settings.settings, pointer)
  return typeof value === 'string' && value.trim() !== '' ? value : null
})

const draft = ref(saved.value ?? '')
// A change from elsewhere (another front end, *Use bundled*) shows unless the user is typing.
watch(saved, (now, before) => {
  if (draft.value === (before ?? '')) draft.value = now ?? ''
})
const shown = computed(() => (byEnvironment.value ? (props.tool.path ?? '') : draft.value))

const bundled = useBundledTools()
const bundledIssues = shallowRef<ValidationIssue[]>([])
/**
 * With a bundled build the reset is *Use bundled*, for the whole family: an ffprobe path left
 * behind would still win over the bundled ffprobe.
 */
const canUseBundled = computed(
  () => props.tool.bundled && !byEnvironment.value && saved.value !== null,
)
/** The other tools of the family whose Settings paths *Use bundled* removes too. */
const alsoReset = computed(() =>
  canUseBundled.value
    ? familyOf(props.tool.name).filter(
        (name) => name !== props.tool.name && resetOps([name], settings.settings?.tools).length > 0,
      )
    : [],
)
const alsoResetNote = computed(() =>
  t('settings.tools.useBundledAlso', { tools: formatList(alsoReset.value, locale.value, 'and') }),
)
const fieldIssues = computed(() => [...override.issues.value, ...bundledIssues.value])

interface Outcome {
  ok: boolean
  text: string
  /** The test saved a path that does not work: what to put back (`null`: automatic). */
  previous: { value: string | null } | null
}
const outcome = shallowRef<Outcome | null>(null)
const testing = ref(false)

function statusText(status: ToolInfo['status']): string {
  switch (status) {
    case 'found':
      return t('settings.tools.status.found')
    case 'missing':
      return t('settings.tools.status.missing')
    case 'too_old':
      return t('settings.tools.status.tooOld')
    case 'broken':
      return t('settings.tools.status.broken')
  }
}
const statusLabel = computed(() => statusText(props.tool.status))

function originText(tool: ToolInfo): string {
  switch (tool.origin) {
    case 'env':
      return t('settings.tools.origin.env', { variable: tool.env_var ?? '' })
    case 'settings':
      return t('settings.tools.origin.settings')
    case 'bundled':
      return t('settings.tools.origin.bundled')
    case 'path':
      return t('settings.tools.origin.path')
    default:
      return t('settings.tools.origin.none')
  }
}
const originLabel = computed(() => originText(props.tool))

const note = computed(() => {
  const variable = props.tool.env_var ?? ''
  if (byEnvironment.value) return t('settings.tools.envNote', { variable })
  if (props.mode === 'web') return t('settings.tools.webNote', { variable })
  return null
})

/** The API client has shown a failed re-scan as a toast. */
async function rescan(): Promise<boolean> {
  try {
    await system.rescanTools()
    return true
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    return false
  }
}

function result(previous: string | null, changed: boolean): Outcome | null {
  const now = system.info?.tools[props.tool.name]
  if (now === undefined) return null
  const ok = now.status === 'found'
  const text = ok
    ? now.version
      ? t('settings.tools.testOk', { version: now.version })
      : t('settings.tools.testOkNoVersion')
    : t('settings.tools.testFailed', { reason: now.reason ?? statusText(now.status) })
  return { ok, text, previous: changed && !ok ? { value: previous } : null }
}

/**
 * The server cannot test a path without using it: a changed path is saved, the tools are
 * found again, and a path that does not work can be put back.
 */
async function test(): Promise<void> {
  if (testing.value) return
  testing.value = true
  outcome.value = null
  try {
    const previous = saved.value
    const wanted = draft.value.trim() === '' ? null : draft.value.trim()
    const changed = editable.value && wanted !== previous
    if (changed && !(await override.save(wanted))) return
    if (!(await rescan())) return
    outcome.value = result(previous, changed)
  } finally {
    testing.value = false
  }
}

async function putBack(previous: string | null): Promise<void> {
  testing.value = true
  try {
    if (!(await override.save(previous))) return
    draft.value = previous ?? ''
    outcome.value = null
    if (await rescan()) outcome.value = result(previous, false)
  } finally {
    testing.value = false
  }
}

async function useBundled(): Promise<void> {
  testing.value = true
  outcome.value = null
  bundledIssues.value = []
  try {
    bundledIssues.value = await bundled.use(props.tool.name)
    if (bundledIssues.value.length === 0) draft.value = ''
  } finally {
    testing.value = false
  }
}

async function remove(): Promise<void> {
  testing.value = true
  outcome.value = null
  bundledIssues.value = []
  try {
    if (!(await override.save(null))) return
    draft.value = ''
    await rescan()
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="tool-row" :data-tool="tool.name">
    <div class="tool-row__head">
      <h3 class="tool-row__name">{{ tool.name }}</h3>
      <StatusDot :tone="toolTone(tool)" :label="statusLabel" show-label />
    </div>
    <dl class="rf-kv-list tool-row__facts">
      <KeyValue :label="t('settings.tools.version')" :value="tool.version" />
      <KeyValue :label="t('settings.tools.from')">
        <span data-field="origin">{{ originLabel }}</span>
        <span v-if="tool.next_to_ffmpeg" class="tool-row__muted">
          {{ t('settings.tools.nextToFfmpeg') }}</span
        >
      </KeyValue>
      <KeyValue :label="t('settings.tools.binary')">
        <code v-if="tool.path" data-field="path">{{ tool.path }}</code>
        <span v-else class="tool-row__muted">{{ t('settings.tools.noBinary') }}</span>
      </KeyValue>
    </dl>
    <p v-if="tool.reason" class="tool-row__reason" data-field="reason">{{ tool.reason }}</p>

    <Field :label="t('settings.tools.override')" :issues="fieldIssues" stacked>
      <template #default="{ id, invalid }">
        <div class="tool-row__override">
          <InputText
            :id="id"
            :model-value="shown"
            :readonly="!editable"
            :invalid="invalid"
            :class="{ 'tool-row__input--readonly': !editable }"
            :placeholder="t('settings.tools.automatic')"
            fluid
            spellcheck="false"
            autocomplete="off"
            data-field="override"
            @update:model-value="draft = $event ?? ''"
            @keydown.enter.prevent="test"
          />
          <Button
            :label="t('settings.tools.test')"
            severity="secondary"
            outlined
            :loading="testing"
            data-action="test"
            @click="test"
          />
          <Button
            v-if="canUseBundled"
            :label="t('settings.tools.useBundledTool')"
            severity="secondary"
            text
            :disabled="locked || testing || bundled.fetching.value"
            data-action="use-bundled"
            @click="useBundled"
          />
          <Button
            v-else-if="saved !== null && !byEnvironment"
            :label="t('settings.tools.removeOverride')"
            severity="secondary"
            text
            :disabled="locked || testing"
            data-action="remove"
            @click="remove"
          />
        </div>
      </template>
    </Field>
    <p v-if="alsoReset.length > 0" class="tool-row__note" data-field="bundled-note">
      {{ alsoResetNote }}
    </p>
    <p v-if="note" class="tool-row__note" data-field="note">{{ note }}</p>

    <div
      v-if="outcome"
      class="tool-row__outcome"
      :class="outcome.ok ? 'tool-row__outcome--ok' : 'tool-row__outcome--error'"
      role="status"
      data-field="outcome"
    >
      <span>{{ outcome.text }}</span>
      <Button
        v-if="outcome.previous"
        :label="
          outcome.previous.value
            ? t('settings.tools.putBack', { path: outcome.previous.value })
            : t('settings.tools.putBackAutomatic')
        "
        size="small"
        :disabled="locked"
        data-action="put-back"
        @click="putBack(outcome.previous.value)"
      />
    </div>
  </div>
</template>

<style scoped>
.tool-row {
  display: grid;
  gap: var(--rf-space-2);
  padding-block: var(--rf-space-3);
  border-top: 1px solid var(--rf-color-border);
}

.tool-row:first-child {
  border-top: 0;
}

.tool-row__head {
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
}

.tool-row__name {
  margin: 0;
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-md);
}

.tool-row__facts code {
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
}

.tool-row__muted,
.tool-row__note {
  color: var(--rf-color-text-muted);
}

.tool-row__note,
.tool-row__reason {
  margin: 0;
  font-size: var(--rf-font-size-sm);
}

.tool-row__override {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.tool-row__override > :first-child {
  flex: 1 1 18rem;
}

.tool-row__input--readonly {
  background: var(--p-inputtext-disabled-background);
  color: var(--rf-color-text-muted);
}

.tool-row__outcome {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
  font-size: var(--rf-font-size-sm);
}

.tool-row__outcome--ok {
  color: var(--p-status-ok-color);
}

.tool-row__outcome--error {
  color: var(--p-status-error-color);
}
</style>
