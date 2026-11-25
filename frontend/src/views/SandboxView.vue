<script setup lang="ts">
import Button from 'primevue/button'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet } from '@/api/client'
import type { Language, NamingOptions, SourceEntry } from '@/api/types'
import Card from '@/components/base/Card.vue'
import Field from '@/components/base/Field.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import Section from '@/components/base/Section.vue'
import JobNamingEditor from '@/components/naming/JobNamingEditor.vue'
import NamingOptionsEditor from '@/components/naming/NamingOptionsEditor.vue'
import { type Density, type ThemeChoice, useTheme } from '@/composables/useTheme'
import { useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import SandboxGallery from './SandboxGallery.vue'
import { useSchemeScopes } from './sandboxScopes'

const { t } = useI18n()
const { theme, density, dark, setTheme, setDensity } = useTheme()
const ui = useUiStore()
const validation = useValidationStore()
const system = useSystemStore()

useSchemeScopes('sandbox-scheme', [dark, density])

const themeOptions = computed(() => [
  { value: 'system' as ThemeChoice, label: t('sandbox.theme.system') },
  { value: 'light' as ThemeChoice, label: t('sandbox.theme.light') },
  { value: 'dark' as ThemeChoice, label: t('sandbox.theme.dark') },
])
const densityOptions = computed(() => [
  { value: 'comfortable' as Density, label: t('sandbox.theme.comfortable') },
  { value: 'compact' as Density, label: t('sandbox.theme.compact') },
])
const schemeInEffect = computed(() =>
  dark.value ? t('sandbox.theme.dark') : t('sandbox.theme.light'),
)

// The validation store is empty without an open job: the sandbox gives one field an issue of
// its own, so that the store path and `ui.reveal` can be tried.
const STORE_PATH = 'sandbox.speed'
validation.issues = [
  {
    severity: 'warning',
    code: 'sandbox.warning',
    path: STORE_PATH,
    message: t('sandbox.field.storeMessage'),
    fixes: [],
  },
]

// Server data stand-ins for when no server is connected.
const SAMPLE_LANGUAGES: Language[] = [
  {
    tag: 'ja',
    iso639_1: 'ja',
    iso639_2b: 'jpn',
    iso639_2t: 'jpn',
    iso639_3: 'jpn',
    english_name: 'Japanese',
    native_name: '日本語',
    variant: false,
  },
  {
    tag: 'en',
    iso639_1: 'en',
    iso639_2b: 'eng',
    iso639_2t: 'eng',
    iso639_3: 'eng',
    english_name: 'English',
    native_name: 'English',
    variant: false,
  },
  {
    tag: 'hu',
    iso639_1: 'hu',
    iso639_2b: 'hun',
    iso639_2t: 'hun',
    iso639_3: 'hun',
    english_name: 'Hungarian',
    native_name: 'magyar',
    variant: false,
  },
  {
    tag: 'de',
    iso639_1: 'de',
    iso639_2b: 'ger',
    iso639_2t: 'deu',
    iso639_3: 'deu',
    english_name: 'German',
    native_name: 'Deutsch',
    variant: false,
  },
  {
    tag: 'pt-BR',
    iso639_1: 'pt',
    iso639_2b: 'por',
    iso639_2t: 'por',
    iso639_3: 'por',
    english_name: 'Portuguese (Brazil)',
    native_name: 'português (Brasil)',
    variant: true,
  },
]
if (system.languages.length === 0) system.languages = SAMPLE_LANGUAGES

const panes = computed(() => [
  { scheme: 'light', title: t('sandbox.theme.light') },
  { scheme: 'dark', title: t('sandbox.theme.dark') },
])

// The naming editors need a server: its sources, and a job opened in the editor store.
const editor = useEditorStore()
const namingSources = ref<SourceEntry[]>([])
const namingSource = ref<string | null>(null)
const namingOptions = ref<NamingOptions>({
  movie_template: '{main_title}',
  episode_template: '{main_title}',
  name_source: 'auto',
  word_separator: 'keep',
  title_case: false,
  replace_underscores: false,
  remove_punctuation: false,
  mp4_extension: 'mp4',
  output_folder_mode: 'same_as_source',
  output_folder: null,
})
// Start from Settings → Output, as the settings page does.
const settingsStore = useSettingsStore()
const stopNamingWatch = watch(
  () => settingsStore.settings?.output?.naming,
  (naming) => {
    if (naming === undefined) return
    namingOptions.value = { ...naming }
    queueMicrotask(() => stopNamingWatch())
  },
  { immediate: true },
)
const namingSourceOptions = computed(() =>
  namingSources.value.map((entry) => ({ value: entry.id, label: entry.path })),
)

async function loadNamingSources(): Promise<void> {
  const result = await apiQuiet.GET('/api/sources')
  namingSources.value = result.data ?? []
  namingSource.value ??= namingSources.value[0]?.id ?? null
}

async function openNamingSource(): Promise<void> {
  if (namingSource.value !== null) await editor.open(namingSource.value)
}

void loadNamingSources().catch(() => undefined)
</script>

<template>
  <main class="sandbox" data-view="sandbox">
    <header class="sandbox__header">
      <h1 class="sandbox__title">{{ t('app.views.sandbox') }}</h1>
      <p class="sandbox__intro">{{ t('sandbox.intro') }}</p>
      <div class="sandbox__switches">
        <Field :label="t('sandbox.theme.label')" stacked>
          <template #default="{ labelId }">
            <SelectButton
              :ariaLabelledby="labelId"
              :model-value="theme"
              :options="themeOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              data-testid="theme"
              @update:model-value="setTheme"
            />
          </template>
        </Field>
        <Field :label="t('sandbox.theme.density')" stacked>
          <template #default="{ labelId }">
            <SelectButton
              :ariaLabelledby="labelId"
              :model-value="density"
              :options="densityOptions"
              option-label="label"
              option-value="value"
              :allow-empty="false"
              data-testid="density"
              @update:model-value="setDensity"
            />
          </template>
        </Field>
        <dl class="rf-kv-list sandbox__in-effect">
          <KeyValue :label="t('sandbox.theme.inEffect')" :value="schemeInEffect" />
        </dl>
        <Button
          :label="t('sandbox.field.reveal')"
          severity="secondary"
          data-testid="reveal"
          @click="ui.reveal(STORE_PATH)"
        />
      </div>
    </header>

    <div class="sandbox__panes">
      <section
        v-for="pane in panes"
        :key="pane.scheme"
        class="sandbox__pane"
        :class="`sandbox-scheme--${pane.scheme}`"
        :aria-label="pane.title"
        :data-scheme="pane.scheme"
      >
        <h2 class="sandbox__pane-title">{{ pane.title }}</h2>
        <SandboxGallery :store-path="STORE_PATH" />
      </section>
    </div>

    <Section :title="t('sandbox.naming.title')" data-testid="naming-sandbox">
      <p class="sandbox__intro">{{ t('sandbox.naming.intro') }}</p>
      <div class="sandbox__row">
        <Field :label="t('sandbox.naming.source')" stacked>
          <template #default="{ id }">
            <Select
              v-model="namingSource"
              :label-id="id"
              :options="namingSourceOptions"
              option-label="label"
              option-value="value"
              :placeholder="t('sandbox.naming.noSources')"
              data-testid="naming-source"
            />
          </template>
        </Field>
        <Button
          :label="t('sandbox.naming.reload')"
          severity="secondary"
          data-testid="naming-reload"
          @click="loadNamingSources"
        />
        <Button
          :label="t('sandbox.naming.open')"
          :disabled="namingSource === null"
          data-testid="naming-open"
          @click="openNamingSource"
        />
      </div>
      <div class="sandbox__naming">
        <Card :title="t('sandbox.naming.options')" data-testid="naming-options">
          <NamingOptionsEditor
            v-model="namingOptions"
            :source-ids="namingSources.map((entry) => entry.id)"
          />
        </Card>
        <Card :title="t('sandbox.naming.job')" data-testid="job-naming">
          <JobNamingEditor />
        </Card>
      </div>
    </Section>
  </main>
</template>

<style scoped>
.sandbox {
  display: grid;
  gap: var(--rf-space-6);
  max-width: 120rem;
  margin: 0 auto;
  padding: var(--rf-space-5);
}

.sandbox__title {
  margin: 0 0 var(--rf-space-2);
  font-size: var(--rf-text-title);
  line-height: var(--rf-line-height-tight);
}

.sandbox__intro {
  max-width: 72ch;
  margin: 0 0 var(--rf-space-4);
  color: var(--rf-color-text-muted);
}

.sandbox__switches {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--rf-space-5);
}

/* The two colour schemes side by side, each on its own ground. */
.sandbox__panes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 36rem), 1fr));
  gap: var(--rf-space-4);
  align-items: start;
}

.sandbox__pane {
  display: grid;
  gap: var(--rf-space-5);
  min-width: 0;
  padding: var(--rf-space-5);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-lg);
  background: var(--rf-color-bg);
  color: var(--rf-color-text);
}

.sandbox__pane-title {
  margin: 0;
  font-size: var(--rf-text-title);
  line-height: var(--rf-line-height-tight);
}

.sandbox__row {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--rf-space-3);
}

.sandbox__naming {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 30rem), 1fr));
  gap: var(--rf-space-4);
  align-items: start;
}
</style>
