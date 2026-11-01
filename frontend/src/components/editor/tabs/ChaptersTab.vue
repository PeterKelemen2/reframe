<script setup lang="ts">
import { Download, RotateCcw, Upload } from '@lucide/vue'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import Menu from 'primevue/menu'
import Message from 'primevue/message'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, reactive, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ChapterFormat, OutputChapter } from '@/api/types'
import Field from '@/components/base/Field.vue'
import IssueList from '@/components/base/IssueList.vue'
import Section from '@/components/base/Section.vue'
import ChapterRow from '@/components/chapters/ChapterRow.vue'
import {
  formatTime,
  importPlan,
  nameSlot,
  namesWith,
  numberedNames,
  shownName,
} from '@/components/chapters/chapters'
import { exportChapters, importChapters } from '@/components/chapters/requests'
import { useOutputChapters } from '@/components/chapters/useOutputChapters'
import { download } from '@/components/presets/format'
import { useJobSource } from '@/components/summary/useJobSource'
import { useReveal } from '@/composables/useReveal'
import { platform } from '@/platform'
import { useEditorStore } from '@/stores/editor'
import { useValidationStore } from '@/stores/validation'

// Reads and writes the editor store; takes no props.
const { t } = useI18n()
const editor = useEditorStore()
const validation = useValidationStore()
const { source } = useJobSource()
const { chapters: answer, failure, pending } = useOutputChapters()

const id = useId()
const root = useTemplateRef<HTMLElement>('root')
const table = useTemplateRef<HTMLElement>('table')
useReveal('chapters', root)
useReveal('chapters.names', table)

const settings = computed(() => editor.job?.chapters ?? null)
const names = computed<string[] | null>(() => settings.value?.names ?? null)
const enabled = computed(() => settings.value?.enabled !== false)
const rows = computed<OutputChapter[]>(() => answer.value?.chapters ?? [])
const generated = computed(() => answer.value?.origin === 'generated')
const nameIssues = computed(() => validation.issuesFor('chapters.names', { nested: true }))

/** The source has no chapters of its own, so the job may generate some. */
const canGenerate = computed(() =>
  source.value !== null
    ? (source.value.chapters ?? []).length === 0
    : (settings.value?.generate_every ?? null) !== null,
)
const DEFAULT_EVERY = 5
let rememberedEvery: number | null = null

function setGenerate(on: boolean): void {
  const current = settings.value?.generate_every ?? null
  if (!on && current !== null) rememberedEvery = current
  editor.set('/chapters/generate_every', on ? (rememberedEvery ?? DEFAULT_EVERY) : null)
}

function setEvery(value: number | null | undefined): void {
  if (typeof value === 'number' && value > 0 && value !== settings.value?.generate_every) {
    editor.set('/chapters/generate_every', value)
  }
}

/** Text typed into a name field that is still focused: the job may show it differently. */
const typed = reactive(new Map<number, string>())

function nameOf(chapter: OutputChapter): string {
  return typed.get(nameSlot(chapter)) ?? shownName(chapter, names.value)
}

function rename(chapter: OutputChapter, name: string): void {
  const slot = nameSlot(chapter)
  typed.set(slot, name)
  editor.set('/chapters/names', namesWith(names.value, rows.value, new Map([[slot, name]])), {
    coalesce: `chapters.names[${slot}]`,
  })
}

function renamed(chapter: OutputChapter): void {
  typed.delete(nameSlot(chapter))
  editor.endCoalescing()
}

interface Notice {
  severity: 'success' | 'warn' | 'error'
  summary: string
  details: string[]
}
const notice = ref<Notice | null>(null)
const busy = ref(false)

watch(
  () => editor.session,
  () => {
    notice.value = null
    typed.clear()
    rememberedEvery = null
  },
)

function reason(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail ?? error.problem.title
  return String(error)
}

const resetMenu = useTemplateRef<InstanceType<typeof Menu>>('resetMenu')
const resetItems = computed(() =>
  generated.value
    ? [
        {
          label: t('chapters.reset.numbered'),
          disabled: names.value === null,
          command: () => editor.set('/chapters/names', null),
        },
      ]
    : [
        {
          label: t('chapters.reset.source'),
          disabled: names.value === null,
          command: () => editor.set('/chapters/names', null),
        },
        {
          label: t('chapters.reset.numbered'),
          command: () =>
            editor.set(
              '/chapters/names',
              numberedNames(names.value, rows.value, (n) =>
                t('chapters.reset.numberedName', { n }),
              ),
            ),
        },
      ],
)

const FORMATS: ChapterFormat[] = ['csv', 'ogm', 'xml']
const MIME: Record<ChapterFormat, string> = {
  csv: 'text/csv;charset=utf-8',
  ogm: 'text/plain;charset=utf-8',
  xml: 'application/xml;charset=utf-8',
}
const exportMenu = useTemplateRef<InstanceType<typeof Menu>>('exportMenu')
const exportItems = computed(() =>
  FORMATS.map((format) => ({
    label: t(`chapters.format.${format}`),
    command: () => void exportAs(format),
  })),
)

async function exportAs(format: ChapterFormat): Promise<void> {
  const job = editor.job
  if (job === null) return
  busy.value = true
  try {
    const file = await exportChapters(job, format)
    download(new Blob([file.content], { type: MIME[format] }), file.file_name)
    notice.value = null
  } catch (error) {
    notice.value = {
      severity: 'error',
      summary: t('chapters.export.failed'),
      details: [reason(error)],
    }
  } finally {
    busy.value = false
  }
}

function fileName(path: string): string {
  return path.split(/[\\/]/).at(-1) ?? path
}

async function importFile(): Promise<void> {
  const session = editor.session
  const [path] = await platform.pickFiles({ multiple: false, filters: ['.csv', '.txt', '.xml'] })
  if (path === undefined || session !== editor.session) return
  busy.value = true
  let imported
  try {
    imported = await importChapters(path)
  } catch (error) {
    if (session === editor.session) {
      notice.value = {
        severity: 'error',
        summary: t('chapters.import.failed'),
        details: [reason(error)],
      }
    }
    return
  } finally {
    busy.value = false
  }
  if (session !== editor.session || editor.job === null) return
  const plan = importPlan(imported.chapters, rows.value)
  if (plan.changes.size > 0) {
    editor.set('/chapters/names', namesWith(names.value, rows.value, plan.changes))
  }
  const details = imported.issues.map((issue) => issue.message)
  if (plan.fileCount !== plan.outputCount) {
    details.push(t('chapters.import.count', { file: plan.fileCount, output: plan.outputCount }))
  }
  for (const moved of plan.moved) {
    details.push(
      t('chapters.import.moved', {
        n: moved.number,
        file: formatTime(moved.file),
        output: formatTime(moved.output),
      }),
    )
  }
  notice.value = {
    severity: details.length > 0 ? 'warn' : 'success',
    summary: t(
      'chapters.import.done',
      { count: plan.changes.size, file: fileName(path) },
      plan.changes.size,
    ),
    details,
  }
}

const hasRows = computed(() => rows.value.length > 0)
</script>

<template>
  <section ref="root" class="editor-tab chapters-tab" data-tab="chapters">
    <p v-if="editor.job === null" class="chapters-tab__empty" data-state="empty">
      {{ editor.loading ? t('chapters.loading') : t('chapters.noJob') }}
    </p>
    <Section v-else :title="t('chapters.title')">
      <template #actions>
        <Button
          size="small"
          severity="secondary"
          :label="t('chapters.import.label')"
          :disabled="!hasRows || busy"
          data-action="import"
          @click="importFile"
        >
          <template #icon><Upload :size="16" aria-hidden="true" /></template>
        </Button>
        <Button
          size="small"
          severity="secondary"
          :label="t('chapters.export.label')"
          :disabled="!hasRows || busy"
          aria-haspopup="true"
          :aria-controls="`${id}-export`"
          data-action="export"
          @click="exportMenu?.toggle($event)"
        >
          <template #icon><Download :size="16" aria-hidden="true" /></template>
        </Button>
        <Menu ref="exportMenu" :pt="{ root: { id: `${id}-export` } }" :model="exportItems" popup />
        <Button
          size="small"
          severity="secondary"
          :label="t('chapters.reset.label')"
          :disabled="!hasRows"
          aria-haspopup="true"
          :aria-controls="`${id}-reset`"
          data-action="reset"
          @click="resetMenu?.toggle($event)"
        >
          <template #icon><RotateCcw :size="16" aria-hidden="true" /></template>
        </Button>
        <Menu ref="resetMenu" :pt="{ root: { id: `${id}-reset` } }" :model="resetItems" popup />
      </template>

      <Field :label="t('chapters.enabled.label')" path="chapters.enabled">
        <template #default="{ id: inputId, labelId }">
          <div class="chapters-tab__inline">
            <ToggleSwitch
              :input-id="inputId"
              :model-value="enabled"
              :ariaLabelledby="labelId"
              data-field="enabled"
              @update:model-value="editor.set('/chapters/enabled', $event)"
            />
            <span class="chapters-tab__hint">{{ t('chapters.enabled.hint') }}</span>
          </div>
        </template>
      </Field>

      <Field
        v-if="canGenerate"
        :label="t('chapters.generate.label')"
        path="chapters.generate_every"
        :help="t('chapters.generate.help')"
      >
        <template #default="{ id: inputId, labelId, invalid }">
          <div class="chapters-tab__inline">
            <ToggleSwitch
              :input-id="inputId"
              :model-value="settings?.generate_every != null"
              :ariaLabelledby="labelId"
              :disabled="!enabled"
              data-field="generate"
              @update:model-value="setGenerate"
            />
            <template v-if="settings?.generate_every != null">
              <span class="chapters-tab__hint">{{ t('chapters.generate.every') }}</span>
              <InputNumber
                class="chapters-tab__every"
                :model-value="settings.generate_every"
                :min="0.5"
                :max="600"
                :max-fraction-digits="2"
                :suffix="` ${t('chapters.generate.unit')}`"
                :ariaLabel="t('chapters.generate.minutes')"
                :invalid="invalid"
                :disabled="!enabled"
                size="small"
                data-field="generate-every"
                @update:model-value="setEvery"
              />
            </template>
          </div>
        </template>
      </Field>

      <Message
        v-if="notice"
        :severity="notice.severity"
        class="chapters-tab__notice"
        closable
        data-state="notice"
        :data-severity="notice.severity"
        @close="notice = null"
      >
        <strong>{{ notice.summary }}</strong>
        <ul v-if="notice.details.length > 0" class="chapters-tab__details">
          <li v-for="(detail, index) in notice.details" :key="index">{{ detail }}</li>
        </ul>
      </Message>

      <IssueList v-if="nameIssues.length > 0" :issues="nameIssues" compact />

      <div ref="table" class="chapters-tab__body" :aria-busy="pending">
        <p v-if="failure !== null" class="chapters-tab__empty" data-state="failed" role="alert">
          {{ t('chapters.state.failed', { reason: failure }) }}
        </p>
        <p v-else-if="answer === null" class="chapters-tab__empty" data-state="asking">
          {{ t('chapters.state.asking') }}
        </p>
        <div v-else-if="!hasRows" class="chapters-tab__none" data-state="none">
          <p class="chapters-tab__none-title">{{ t('chapters.state.none') }}</p>
          <p v-if="answer.reason" class="chapters-tab__empty" data-field="reason">
            {{ answer.reason }}
          </p>
        </div>
        <template v-else>
          <p class="chapters-tab__origin" data-field="origin" :data-origin="answer.origin">
            {{
              generated
                ? t('chapters.origin.generated', { count: rows.length }, rows.length)
                : t('chapters.origin.source', { count: rows.length }, rows.length)
            }}
          </p>
          <div class="chapters-tab__scroll" :class="{ 'chapters-tab__scroll--pending': pending }">
            <table class="chapters-tab__table">
              <caption class="rf-sr-only">
                {{
                  t('chapters.table.caption')
                }}
              </caption>
              <thead>
                <tr>
                  <th scope="col" class="chapters-tab__number">{{ t('chapters.table.number') }}</th>
                  <th scope="col">{{ t('chapters.table.start') }}</th>
                  <th scope="col">{{ t('chapters.table.duration') }}</th>
                  <th scope="col">{{ t('chapters.table.name') }}</th>
                </tr>
              </thead>
              <tbody>
                <ChapterRow
                  v-for="chapter in rows"
                  :key="chapter.number"
                  :chapter="chapter"
                  :name="nameOf(chapter)"
                  @rename="rename(chapter, $event)"
                  @done="renamed(chapter)"
                />
              </tbody>
            </table>
          </div>
        </template>
      </div>
    </Section>
  </section>
</template>

<style scoped>
.chapters-tab {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--rf-space-5);
  padding: var(--rf-space-4);
}

.chapters-tab__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.chapters-tab__inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.chapters-tab__hint {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.chapters-tab__every {
  width: 9rem;
}

.chapters-tab__every :deep(input) {
  width: 100%;
}

.chapters-tab__details {
  margin: var(--rf-space-1) 0 0;
  padding-inline-start: var(--rf-space-4);
}

.chapters-tab__body {
  display: grid;
  gap: var(--rf-space-2);
}

.chapters-tab__none {
  display: grid;
  gap: var(--rf-space-1);
  padding: var(--rf-space-4);
  border: 1px dashed var(--rf-color-border);
  border-radius: var(--rf-radius-md);
}

.chapters-tab__none-title {
  margin: 0;
  font-weight: var(--rf-font-weight-medium);
}

.chapters-tab__origin {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

/* Size containment: the table scrolls inside the tab instead of widening it. */
.chapters-tab__scroll {
  contain: inline-size;
  overflow-x: auto;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  transition: opacity var(--rf-duration) ease;
}

.chapters-tab__scroll--pending {
  opacity: 0.7;
}

.chapters-tab__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--rf-font-size-sm);
}

th {
  padding: var(--rf-space-2);
  border-bottom: 1px solid var(--rf-color-border);
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-medium);
  text-align: start;
  white-space: nowrap;
}

th.chapters-tab__number {
  text-align: end;
}
</style>
