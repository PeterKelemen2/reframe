<script setup lang="ts">
import { FolderOpen } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, onScopeDispose, ref, shallowRef, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NameResult, NamingOptions, ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { latestRequest } from '@/editor/latest'
import { platform } from '@/platform'
import { useSystemStore } from '@/stores/system'
import { useToastStore } from '@/stores/toasts'

import Disclosure from './Disclosure.vue'
import NamingIssues from './NamingIssues.vue'
import ParsedNamePanel from './ParsedNamePanel.vue'
import {
  failureText,
  isTemplateIssue,
  PREVIEW_DEBOUNCE,
  previewNames,
  templateIssues,
  unique,
} from './preview'
import TemplateField from './TemplateField.vue'
import TemplateFixes from './TemplateFixes.vue'
import VariableChips from './VariableChips.vue'

/**
 * The naming templates and options (Settings → Output, the preset editor): template fields
 * with `{` completion and variable chips, the options, and a live preview for `sourceIds`.
 * Every change emits a new object; the given one is never changed.
 */
const props = defineProps<{
  /** Sources whose values the chips and the preview show; empty: no preview. */
  sourceIds?: string[]
  container?: 'mkv' | 'mp4' | 'webm'
  disabled?: boolean
  /** Variable chips and the parsed name start folded (a narrow place). */
  compact?: boolean
}>()

const model = defineModel<NamingOptions>({ required: true })

const { t } = useI18n()
const system = useSystemStore()
const toasts = useToastStore()

type TemplateKey = 'movie_template' | 'episode_template'

const movieField = useTemplateRef<InstanceType<typeof TemplateField>>('movieField')
const episodeField = useTemplateRef<InstanceType<typeof TemplateField>>('episodeField')
/** Where a chip inserts its variable: the template field that had the focus last. */
const lastTemplate = ref<TemplateKey>('movie_template')
const chipsOpen = ref(!props.compact)
const parsedOpen = ref(!props.compact)

function set<K extends keyof NamingOptions>(key: K, value: NamingOptions[K]): void {
  model.value = { ...model.value, [key]: value }
}

function insertVariable(name: string): void {
  const target = lastTemplate.value === 'movie_template' ? movieField.value : episodeField.value
  target?.insert(`{${name}}`)
}

const nameSources = computed(() => [
  { value: 'auto', label: t('naming.source.auto') },
  { value: 'file', label: t('naming.source.file') },
  { value: 'folder', label: t('naming.source.folder') },
])
const separators = computed(() => [
  { value: 'keep', label: t('naming.separator.keep') },
  { value: 'space', label: t('naming.separator.space') },
  { value: 'dot', label: t('naming.separator.dot') },
  { value: 'underscore', label: t('naming.separator.underscore') },
])
const extensions = computed(() => [
  { value: 'mp4', label: t('naming.options.extMp4') },
  { value: 'm4v', label: t('naming.options.extM4v') },
  { value: 'auto', label: t('naming.options.extAuto') },
])
const folderModes = computed(() => [
  { value: 'fixed', label: t('naming.folder.fixed') },
  { value: 'same_as_source', label: t('naming.folder.sameAsSource') },
])

async function browse(): Promise<void> {
  let folder: string | null
  try {
    folder = await platform.pickFolder({ title: t('naming.folder.pickTitle') })
  } catch {
    toasts.push({ severity: 'warn', summary: t('naming.folder.pickFailed'), life: 8000 })
    return
  }
  if (folder !== null) set('output_folder', folder)
}

interface Preview {
  results: NameResult[]
  movie: ValidationIssue[]
  episode: ValidationIssue[]
}

const results = shallowRef<NameResult[]>([])
const movieIssues = shallowRef<ValidationIssue[]>([])
const episodeIssues = shallowRef<ValidationIssue[]>([])
const pending = ref(false)
const failure = ref<string | null>(null)
const selected = ref(0)

const runner = latestRequest<Preview>({
  async send(signal) {
    const ids = props.sourceIds ?? []
    const naming = model.value
    const container = props.container ?? 'mkv'
    if (ids.length === 0) return { results: [], movie: [], episode: [] }
    const named = await previewNames({ naming, source_ids: ids, container }, signal)
    // A source shows only the issues of the template it used: a template no source used is
    // checked on the first source as if it were the only template.
    const known = new Map<string, ValidationIssue[]>()
    for (const kind of ['movie', 'episode'] as const) {
      const used = named.filter((result) => result.template_kind === kind)
      if (used.length > 0) known.set(naming[`${kind}_template`], templateIssues(used))
    }
    const issuesOf = async (key: TemplateKey): Promise<ValidationIssue[]> => {
      const template = naming[key]
      const issues = known.get(template)
      if (issues !== undefined) return issues
      const check = await previewNames(
        {
          naming: { ...naming, movie_template: template, episode_template: template },
          source_ids: ids.slice(0, 1),
          container,
        },
        signal,
      )
      return templateIssues(check)
    }
    const [movie, episode] = await Promise.all([
      issuesOf('movie_template'),
      issuesOf('episode_template'),
    ])
    return { results: named, movie, episode }
  },
  done(preview) {
    results.value = preview.results
    movieIssues.value = preview.movie
    episodeIssues.value = preview.episode
    pending.value = false
    failure.value = null
  },
  failed(error) {
    pending.value = false
    failure.value = failureText(error) ?? t('naming.preview.failed')
  },
})
onScopeDispose(() => runner.cancel())

let first = true
watch(
  () => JSON.stringify([model.value, props.sourceIds ?? [], props.container ?? 'mkv']),
  () => {
    pending.value = (props.sourceIds ?? []).length > 0
    runner.schedule(first ? 0 : PREVIEW_DEBOUNCE)
    first = false
  },
  { immediate: true },
)

const current = computed<NameResult | null>(
  () => results.value[Math.min(selected.value, results.value.length - 1)] ?? null,
)
const folderIssues = computed(() =>
  unique(
    results.value
      .flatMap((result) => result.issues ?? [])
      .filter((issue) => issue.path === 'naming.output_folder'),
  ),
)
const otherIssues = computed(() =>
  unique(
    results.value
      .flatMap((result) => result.issues ?? [])
      .filter((issue) => !isTemplateIssue(issue) && issue.path !== 'naming.output_folder'),
  ),
)

function fileOf(result: NameResult): string {
  const path = result.candidates?.[0]?.path ?? ''
  return path.split(/[/\\]/).at(-1) ?? path
}
</script>

<template>
  <div class="naming-options" :class="{ 'naming-options--disabled': disabled }">
    <Field
      :label="t('naming.options.movieTemplate')"
      path="naming.movie_template"
      :issues="movieIssues"
      stacked
    >
      <template #default="{ id, invalid }">
        <TemplateField
          :id="id"
          ref="movieField"
          :model-value="model.movie_template"
          :variables="system.namingVariables"
          :invalid="invalid"
          :disabled="disabled"
          data-template="movie"
          @update:model-value="set('movie_template', $event)"
          @focus="lastTemplate = 'movie_template'"
        />
        <TemplateFixes
          :issues="movieIssues"
          :disabled="disabled"
          @use="set('movie_template', $event)"
        />
      </template>
    </Field>
    <Field
      :label="t('naming.options.episodeTemplate')"
      :help="t('naming.options.episodeHelp')"
      path="naming.episode_template"
      :issues="episodeIssues"
      stacked
    >
      <template #default="{ id, invalid }">
        <TemplateField
          :id="id"
          ref="episodeField"
          :model-value="model.episode_template"
          :variables="system.namingVariables"
          :invalid="invalid"
          :disabled="disabled"
          data-template="episode"
          @update:model-value="set('episode_template', $event)"
          @focus="lastTemplate = 'episode_template'"
        />
        <TemplateFixes
          :issues="episodeIssues"
          :disabled="disabled"
          @use="set('episode_template', $event)"
        />
      </template>
    </Field>

    <Disclosure v-model:open="chipsOpen" :title="t('naming.chips.title')">
      <VariableChips
        :variables="system.namingVariables"
        :values="current?.variables ?? null"
        :disabled="disabled"
        @insert="insertVariable"
      />
    </Disclosure>

    <div class="naming-options__grid">
      <Field :label="t('naming.options.nameSource')" stacked>
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="model.name_source"
            :options="nameSources"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="disabled"
            data-option="name_source"
            @update:model-value="set('name_source', $event)"
          />
        </template>
      </Field>
      <Field :label="t('naming.options.separator')" stacked>
        <template #default="{ id, labelId }">
          <Select
            :label-id="id"
            :ariaLabelledby="labelId"
            :model-value="model.word_separator"
            :options="separators"
            option-label="label"
            option-value="value"
            :disabled="disabled"
            data-option="word_separator"
            @update:model-value="set('word_separator', $event)"
          />
        </template>
      </Field>
      <Field :label="t('naming.options.titleCase')">
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="model.title_case"
            :disabled="disabled"
            data-option="title_case"
            @update:model-value="set('title_case', $event)"
          />
        </template>
      </Field>
      <Field :label="t('naming.options.replaceUnderscores')">
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="model.replace_underscores"
            :disabled="disabled"
            data-option="replace_underscores"
            @update:model-value="set('replace_underscores', $event)"
          />
        </template>
      </Field>
      <Field :label="t('naming.options.removePunctuation')">
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="model.remove_punctuation"
            :disabled="disabled"
            data-option="remove_punctuation"
            @update:model-value="set('remove_punctuation', $event)"
          />
        </template>
      </Field>
      <Field :label="t('naming.options.mp4Extension')" :help="t('naming.options.mp4Help')" stacked>
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="model.mp4_extension"
            :options="extensions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="disabled"
            data-option="mp4_extension"
            @update:model-value="set('mp4_extension', $event)"
          />
        </template>
      </Field>
    </div>

    <Field :label="t('naming.folder.mode')" stacked>
      <template #default="{ labelId }">
        <SelectButton
          :ariaLabelledby="labelId"
          :model-value="model.output_folder_mode"
          :options="folderModes"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          :disabled="disabled"
          data-option="output_folder_mode"
          @update:model-value="set('output_folder_mode', $event)"
        />
      </template>
    </Field>
    <Field
      v-if="model.output_folder_mode === 'fixed'"
      :label="t('naming.folder.folder')"
      path="naming.output_folder"
      :issues="folderIssues"
      stacked
    >
      <template #default="{ id, invalid }">
        <div class="naming-options__folder">
          <InputText
            :id="id"
            :model-value="model.output_folder ?? ''"
            :invalid="invalid"
            :disabled="disabled"
            fluid
            data-option="output_folder"
            @update:model-value="set('output_folder', $event ? $event : null)"
          />
          <Button
            :label="t('naming.folder.browse')"
            severity="secondary"
            outlined
            :disabled="disabled"
            data-action="browse"
            @click="browse"
          >
            <template #icon>
              <FolderOpen :size="16" aria-hidden="true" />
            </template>
          </Button>
        </div>
      </template>
    </Field>

    <section class="naming-options__preview" :aria-label="t('naming.preview.title')">
      <div class="naming-options__preview-head">
        <h4>{{ t('naming.preview.title') }}</h4>
        <span class="naming-options__status" aria-live="polite">{{
          pending ? t('naming.preview.updating') : ''
        }}</span>
      </div>
      <p v-if="(sourceIds ?? []).length === 0" class="naming-options__empty">
        {{ t('naming.preview.noSource') }}
      </p>
      <p v-else-if="failure !== null" class="naming-options__failure" role="alert">
        {{ t('naming.preview.failedWith', { reason: failure }) }}
      </p>
      <template v-else>
        <ul class="naming-options__results" data-testid="naming-results">
          <li v-for="(result, index) in results" :key="index">
            <button
              type="button"
              class="naming-options__result"
              :aria-pressed="current === result"
              @click="selected = index"
            >
              <span class="naming-options__file">{{ fileOf(result) }}</span>
              <span class="naming-options__arrow" aria-hidden="true">→</span>
              <code class="naming-options__name" data-testid="naming-result">{{
                result.relative_path
              }}</code>
            </button>
          </li>
        </ul>
        <NamingIssues :issues="otherIssues" />
        <Disclosure
          v-if="current !== null"
          v-model:open="parsedOpen"
          :title="t('naming.parsed.title', { file: fileOf(current) })"
        >
          <ParsedNamePanel :result="current" />
        </Disclosure>
      </template>
    </section>
  </div>
</template>

<style scoped>
.naming-options {
  display: grid;
  gap: var(--rf-space-4);
  min-width: 0;
}

.naming-options__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
  gap: var(--rf-space-3) var(--rf-space-5);
}

.naming-options__folder {
  display: flex;
  gap: var(--rf-space-2);
}

.naming-options__preview {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
  padding-top: var(--rf-space-2);
  border-top: 1px solid var(--rf-color-border);
}

.naming-options__preview-head {
  display: flex;
  align-items: baseline;
  gap: var(--rf-space-3);
}

.naming-options__preview-head h4 {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.naming-options__status,
.naming-options__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.naming-options__failure {
  margin: 0;
  color: var(--p-status-error-color);
}

.naming-options__results {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.naming-options__result {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--rf-space-1) var(--rf-space-2);
  width: 100%;
  padding: var(--rf-space-1) var(--rf-space-2);
  border: 1px solid transparent;
  border-radius: var(--rf-radius-md);
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.naming-options__result[aria-pressed='true'] {
  border-color: var(--rf-color-primary);
}

.naming-options__result:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 1px;
}

.naming-options__file {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  overflow-wrap: anywhere;
}

.naming-options__name {
  font-family: var(--rf-font-mono);
  font-weight: var(--rf-font-weight-medium);
  overflow-wrap: anywhere;
}
</style>
