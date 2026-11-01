<script setup lang="ts">
import Checkbox from 'primevue/checkbox'
import Select from 'primevue/select'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import Field from '@/components/base/Field.vue'
import { describeTag } from '@/components/language/catalog'
import LanguageListEditor from '@/components/language/LanguageListEditor.vue'
import { useDefaultsStore } from '@/stores/defaults'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

import IssueLines from './IssueLines.vue'
import type { TrackSelection } from './model'
import { type Option, useDefaultsOptions } from './options'

/** Which source tracks the defaults take: shared by the audio and the subtitle defaults. */
const { t } = useI18n()
const defaults = useDefaultsStore()
const settings = useSettingsStore()
const system = useSystemStore()
const choices = useDefaultsOptions()
const id = useId()

const audio = computed(() => defaults.kind === 'audio')
const member = computed(() => (audio.value ? 'audio_defaults' : 'subtitle_defaults'))
const selection = computed(
  () => (audio.value ? defaults.audio?.selection : defaults.subtitles?.selection) as TrackSelection,
)
const container = computed(() => defaults.container ?? undefined)

function update<K extends keyof TrackSelection>(key: K, value: TrackSelection[K]): void {
  const next = { ...selection.value, [key]: value }
  if (audio.value && defaults.audio !== null) {
    defaults.setAudio({ ...defaults.audio, selection: next })
  } else if (!audio.value && defaults.subtitles !== null) {
    defaults.setSubtitles({ ...defaults.subtitles, selection: next })
  }
}

const preferred = computed(() => {
  const languages = settings.settings?.languages
  return (audio.value ? languages?.preferred_audio : languages?.preferred_subtitle) ?? []
})
const fromSettings = computed(() => (selection.value.languages ?? null) === null)
const preferredText = computed(() => {
  if (preferred.value.length === 0) return t('defaults.selection.noneSet')
  const names = preferred.value.map(
    (tag) => describeTag(system.languages, tag)?.english_name ?? tag,
  )
  return t('defaults.selection.settingsList', { languages: names.join(', ') })
})

function useSettings(checked: boolean): void {
  update('languages', checked ? null : [...preferred.value])
}

interface SelectField {
  key: Exclude<keyof TrackSelection, 'languages'>
  label: string
  options: Option<string>[]
  help?: string
}

const fields = computed<SelectField[]>(() => [
  {
    key: 'tracks_per_language',
    label: t('defaults.selection.tracksPerLanguage'),
    options: choices.tracksPerLanguage,
  },
  {
    key: 'tie_break',
    label: t('defaults.selection.tieBreak'),
    options: choices.tieBreak,
    help: t('defaults.selection.tieBreakHelp'),
  },
  {
    key: 'undetermined',
    label: t('defaults.selection.undetermined'),
    options: choices.undetermined,
  },
  {
    key: 'other_languages',
    label: t('defaults.selection.otherLanguages'),
    options: choices.otherLanguages,
  },
  { key: 'no_match', label: t('defaults.selection.noMatch'), options: choices.noMatch },
  {
    key: 'commentary',
    label: audio.value
      ? t('defaults.selection.commentaryAudio')
      : t('defaults.selection.commentary'),
    options: choices.commentary,
  },
  { key: 'order', label: t('defaults.selection.order'), options: choices.order },
  {
    key: 'default_track',
    label: t('defaults.selection.defaultTrack'),
    options: choices.defaultTrack(defaults.kind, selection.value.default_track),
  },
])
</script>

<template>
  <div class="defaults-selection">
    <fieldset
      class="defaults-selection__languages"
      :data-path="`${member}.selection.languages`"
      :aria-describedby="`${id}-languages-text`"
    >
      <legend class="defaults-selection__legend">{{ t('defaults.selection.languages') }}</legend>
      <span class="defaults-selection__check">
        <Checkbox
          :input-id="`${id}-settings`"
          binary
          :model-value="fromSettings"
          :disabled="defaults.readOnly"
          data-role="languages-from-settings"
          @update:model-value="useSettings($event === true)"
        />
        <label :for="`${id}-settings`">
          {{
            audio ? t('defaults.selection.fromSettingsAudio') : t('defaults.selection.fromSettings')
          }}
        </label>
      </span>
      <p :id="`${id}-languages-text`" class="defaults-selection__hint">
        <template v-if="fromSettings">{{ preferredText }}</template>
        <template v-else-if="(selection.languages ?? []).length === 0">
          {{ t('defaults.selection.emptyList') }}
        </template>
      </p>
      <LanguageListEditor
        v-if="!fromSettings"
        :model-value="selection.languages ?? []"
        :label="t('defaults.selection.languages')"
        :disabled="defaults.readOnly"
        :container="container"
        @update:model-value="update('languages', $event)"
      />
      <IssueLines :issues="defaults.issuesAt(`${member}.selection.languages`)" />
    </fieldset>
    <div class="defaults-selection__grid">
      <Field
        v-for="field in fields"
        :key="field.key"
        :label="field.label"
        :help="field.help"
        :path="`${member}.selection.${field.key}`"
        :issues="defaults.issuesAt(`${member}.selection.${field.key}`)"
        stacked
      >
        <template #default="{ id: inputId, labelId, invalid }">
          <Select
            :input-id="inputId"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            :model-value="selection[field.key]"
            :options="field.options"
            option-label="label"
            option-value="value"
            :disabled="defaults.readOnly"
            fluid
            :data-field="field.key"
            @update:model-value="update(field.key, $event)"
          />
        </template>
      </Field>
    </div>
  </div>
</template>

<style scoped>
.defaults-selection {
  display: grid;
  gap: var(--rf-space-4);
}

.defaults-selection__languages {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.defaults-selection__legend {
  margin-bottom: var(--rf-space-1);
  padding: 0;
  font-weight: var(--rf-font-weight-medium);
}

.defaults-selection__check {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.defaults-selection__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.defaults-selection__hint:empty {
  display: none;
}

.defaults-selection__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
  gap: var(--rf-space-3) var(--rf-space-4);
}
</style>
