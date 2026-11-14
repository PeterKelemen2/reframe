<script setup lang="ts">
import { Copy } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import { computed, nextTick, onMounted, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError, apiQuiet, unwrap } from '@/api/client'
import type { Schemas, ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import { platform } from '@/platform'

import { useSetting, useSettingsLocked } from './useSetting'

type LogLevel = Schemas['DiagnosticsSettings']['log_level']
type Report = Schemas['DiagnosticsReport']

const { t } = useI18n()
const locked = useSettingsLocked()
const logLevel = useSetting<LogLevel>('/diagnostics/log_level')

const levels = computed<{ value: LogLevel; label: string }[]>(() => [
  { value: 'error', label: t('settings.diagnostics.level.error') },
  { value: 'warning', label: t('settings.diagnostics.level.warning') },
  { value: 'info', label: t('settings.diagnostics.level.info') },
  { value: 'debug', label: t('settings.diagnostics.level.debug') },
])

const id = useId()
const logsDescriptionId = `${id}-logs`
const copyHelpId = `${id}-copy`
const reportId = `${id}-report`

const logsDir = ref<string | null>(null)
const logsDirFailure = ref<string | null>(null)
const logsDirIssues = computed<ValidationIssue[]>(() =>
  logsDirFailure.value === null
    ? []
    : [
        {
          severity: 'error',
          code: 'diagnostics.unreadable',
          path: 'diagnostics.logs_dir',
          message: t('settings.diagnostics.logsFolderFailed', { reason: logsDirFailure.value }),
          fixes: [],
        },
      ],
)

type CopyState = 'idle' | 'busy' | 'copied' | 'copyFailed' | 'readFailed'
const copyState = ref<CopyState>('idle')
const readFailure = ref('')
/** The report with its client part, shown when the clipboard refused it. */
const shownReport = ref<string | null>(null)

const status = computed(() => {
  switch (copyState.value) {
    case 'busy':
      return t('settings.diagnostics.reading')
    case 'copied':
      return t('settings.diagnostics.copied')
    case 'copyFailed':
      return t('settings.diagnostics.copyFailed')
    case 'readFailed':
      return t('settings.diagnostics.readFailed', { reason: readFailure.value })
    default:
      return ''
  }
})

function reason(error: ApiError): string {
  const { title, detail } = error.problem
  return detail ? t('settings.refusedWithDetail', { title, detail }) : title
}

async function readReport(): Promise<Report> {
  return unwrap(await apiQuiet.GET('/api/diagnostics'))
}

/** What only the page knows. Not translated: whoever handles the bug report reads it. */
function clientPart(): string {
  return [
    'Client',
    `  Kind: ${platform.kind}`,
    `  User agent: ${navigator.userAgent}`,
    `  Device pixel ratio: ${globalThis.devicePixelRatio}`,
  ].join('\n')
}

onMounted(async () => {
  try {
    logsDir.value = (await readReport()).logs_dir
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    logsDirFailure.value = reason(error)
  }
})

/** Reads the report when pressed, so it holds the state at that moment. */
async function copyDiagnostics(): Promise<void> {
  if (copyState.value === 'busy') return
  copyState.value = 'busy'
  shownReport.value = null
  let report: Report
  try {
    report = await readReport()
  } catch (error) {
    if (!(error instanceof ApiError)) {
      copyState.value = 'idle'
      throw error
    }
    readFailure.value = reason(error)
    copyState.value = 'readFailed'
    return
  }
  logsDir.value = report.logs_dir
  logsDirFailure.value = null
  const text = `${report.text.trimEnd()}\n\n${clientPart()}\n`
  try {
    // Undefined outside a secure context (a web server reached over plain http): that throws too.
    await navigator.clipboard.writeText(text)
    copyState.value = 'copied'
  } catch {
    shownReport.value = text
    copyState.value = 'copyFailed'
    await nextTick()
    const box = document.getElementById(reportId) as HTMLTextAreaElement | null
    box?.focus()
    box?.select()
  }
}
</script>

<template>
  <Section :title="t('settings.diagnostics.title')">
    <div class="diagnostics-section__fields">
      <Field
        :label="t('settings.diagnostics.logLevel')"
        :help="t('settings.diagnostics.logLevelHelp')"
        :issues="logLevel.issues.value"
      >
        <template #default="{ id: fieldId, labelId, invalid }">
          <Select
            :label-id="fieldId"
            :ariaLabelledby="labelId"
            :model-value="logLevel.value.value ?? 'info'"
            :options="levels"
            option-label="label"
            option-value="value"
            :invalid="invalid"
            :disabled="locked"
            data-field="log-level"
            @update:model-value="logLevel.save($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.diagnostics.logsFolder')"
        :description="logsDescriptionId"
        :issues="logsDirIssues"
      >
        <template #default="{ id: fieldId }">
          <div class="diagnostics-section__logs">
            <InputText
              :id="fieldId"
              :model-value="logsDir ?? ''"
              :placeholder="
                logsDir === null && logsDirFailure === null
                  ? t('settings.diagnostics.logsFolderLoading')
                  : undefined
              "
              readonly
              fluid
              spellcheck="false"
              data-field="logs-dir"
            />
            <p :id="logsDescriptionId" class="diagnostics-section__note">
              {{ t('settings.diagnostics.logsFolderHelp') }}
            </p>
          </div>
        </template>
      </Field>
      <div class="diagnostics-section__copy">
        <div class="diagnostics-section__copy-row">
          <Button
            severity="secondary"
            :label="t('settings.diagnostics.copy')"
            :aria-busy="copyState === 'busy'"
            :aria-describedby="copyHelpId"
            data-action="copy-diagnostics"
            @click="copyDiagnostics"
          >
            <template #icon><Copy :size="16" aria-hidden="true" /></template>
          </Button>
          <p
            class="diagnostics-section__status"
            :data-state="copyState"
            role="status"
            data-field="copy-status"
          >
            {{ status }}
          </p>
        </div>
        <p :id="copyHelpId" class="diagnostics-section__note">
          {{ t('settings.diagnostics.copyHelp') }}
        </p>
        <template v-if="shownReport !== null">
          <label :for="reportId" class="diagnostics-section__report-label">
            {{ t('settings.diagnostics.report') }}
          </label>
          <Textarea
            :id="reportId"
            :model-value="shownReport"
            readonly
            rows="12"
            fluid
            spellcheck="false"
            class="diagnostics-section__report"
            data-field="report"
          />
        </template>
      </div>
    </div>
  </Section>
</template>

<style scoped>
.diagnostics-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}

.diagnostics-section__logs,
.diagnostics-section__copy {
  display: grid;
  gap: var(--rf-space-1);
  min-width: 0;
}

.diagnostics-section__copy-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-3);
}

.diagnostics-section__note,
.diagnostics-section__status {
  margin: 0;
}

.diagnostics-section__note {
  color: var(--rf-color-text-muted);
}
.diagnostics-section__status[data-state='copyFailed'],
.diagnostics-section__status[data-state='readFailed'] {
  color: var(--p-status-error-color);
}

.diagnostics-section__report-label {
  margin-top: var(--rf-space-2);
  font-weight: var(--rf-font-weight-medium);
}

.diagnostics-section__report {
  font-family: var(--rf-font-mono);
}
</style>
