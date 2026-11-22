<script setup lang="ts">
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet } from '@/api/client'
import type {
  Language,
  NamingOptions,
  SourceEntry,
  TrackRoleInfo,
  ValidationIssue,
} from '@/api/types'
import Card from '@/components/base/Card.vue'
import CodecLabel from '@/components/base/CodecLabel.vue'
import Field from '@/components/base/Field.vue'
import IssueList from '@/components/base/IssueList.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import LanguageChip from '@/components/base/LanguageChip.vue'
import RoleBadge from '@/components/base/RoleBadge.vue'
import Section from '@/components/base/Section.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import type { CodecInfo, StatusTone } from '@/components/base/types'
import JobNamingEditor from '@/components/naming/JobNamingEditor.vue'
import NamingOptionsEditor from '@/components/naming/NamingOptionsEditor.vue'
import { type Density, type ThemeChoice, useTheme } from '@/composables/useTheme'
import { useEditorStore } from '@/stores/editor'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

const { t, locale } = useI18n()
const { theme, density, dark, setTheme, setDensity } = useTheme()
const ui = useUiStore()
const validation = useValidationStore()
const system = useSystemStore()

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

function issue(severity: ValidationIssue['severity'], message: string, path = ''): ValidationIssue {
  return { severity, code: `sandbox.${severity}`, path, message, fixes: [] }
}

const errorIssues = computed(() => [issue('error', t('sandbox.field.errorMessage'))])
const warningIssues = computed(() => [issue('warning', t('sandbox.field.warningMessage'))])
const infoIssues = computed(() => [issue('info', t('sandbox.field.infoMessage'))])

// The validation store is empty without an open job: the sandbox gives one field an issue of
// its own, so that the store path and `ui.reveal` can be tried.
const STORE_PATH = 'sandbox.speed'
validation.issues = [issue('warning', t('sandbox.field.storeMessage'), STORE_PATH)]

const listIssues = computed<ValidationIssue[]>(() => [
  issue('info', t('sandbox.field.infoMessage'), 'video.frame_rate'),
  issue('warning', t('sandbox.field.warningMessage'), 'audio[1].bitrate'),
  {
    ...issue('error', t('sandbox.field.errorMessage'), STORE_PATH),
    fixes: [
      { label: t('sandbox.issues.fixFallback'), patch: [], target: 'job' },
      { label: t('sandbox.issues.fixChoose'), patch: [], target: 'job' },
    ],
  },
  issue('warning', t('sandbox.field.storeMessage')),
])

const encoder = ref('libx265')
const encoders = ['libx264', 'libx265', 'libsvtav1']
const bitrate = ref(128)
const toggle = ref(true)
const folder = ref<string | undefined>('/media/out')
const collapsed = ref(false)

const ROLES: TrackRoleInfo['role'][] = [
  'main',
  'commentary',
  'description',
  'music',
  'sdh',
  'forced',
  'signs',
]
const evidenceRows = computed(() => [
  {
    evidence: 'flag' as const,
    label: t('sandbox.role.flag'),
    detail: t('sandbox.role.detailFlag'),
  },
  {
    evidence: 'title' as const,
    label: t('sandbox.role.byTitle'),
    detail: t('sandbox.role.detailTitle'),
  },
  {
    evidence: 'heuristic' as const,
    label: t('sandbox.role.heuristic'),
    detail: t('sandbox.role.detailHeuristic'),
  },
])

const CODECS: CodecInfo[] = [
  {
    display_codec: 'DTS-HD MA',
    codec: 'dts',
    codec_long: 'DCA (DTS Coherent Acoustics)',
    profile: 'DTS-HD MA',
  },
  { display_codec: 'TrueHD Atmos', codec: 'truehd', codec_long: 'TrueHD', profile: null },
  { display_codec: 'HEVC Main 10', codec: 'hevc', codec_long: 'H.265 / HEVC', profile: 'Main 10' },
  { display_codec: null, codec: 'pcm_s24le', codec_long: null, profile: null },
  {},
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
const LANGUAGE_TAGS = ['jpn', 'en', 'hun', 'ger', 'pt-BR', 'xyz', 'und', null]

const TONES: StatusTone[] = ['ok', 'busy', 'warn', 'error', 'off']
const toneLabel = computed<Record<StatusTone, string>>(() => ({
  ok: t('sandbox.status.ok'),
  busy: t('sandbox.status.busy'),
  warn: t('sandbox.status.warn'),
  error: t('sandbox.status.error'),
  off: t('sandbox.status.off'),
}))

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
      <h1>{{ t('app.views.sandbox') }}</h1>
      <p>{{ t('sandbox.intro') }}</p>
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
      </div>
    </header>

    <Section :title="t('sandbox.tokens.title')">
      <div class="sandbox__row">
        <span class="sandbox__swatch">{{ t('sandbox.tokens.text') }}</span>
        <span class="sandbox__swatch sandbox__swatch--muted">{{ t('sandbox.tokens.muted') }}</span>
        <span class="sandbox__swatch sandbox__swatch--primary">{{
          t('sandbox.tokens.primary')
        }}</span>
        <span
          v-for="tone in TONES"
          :key="tone"
          class="sandbox__swatch"
          :style="{
            color: `var(--p-status-${tone}-color)`,
            background: `var(--p-status-${tone}-background)`,
            borderColor: `var(--p-status-${tone}-border-color)`,
          }"
          >{{ toneLabel[tone] }}</span
        >
      </div>
      <p class="sandbox__type sandbox__type--xl">{{ t('sandbox.tokens.sample') }}</p>
      <p class="sandbox__type sandbox__type--md">{{ t('sandbox.tokens.sample') }}</p>
      <p class="sandbox__type sandbox__type--sm">{{ t('sandbox.tokens.sample') }}</p>
    </Section>

    <Section :title="t('sandbox.field.title')">
      <div class="sandbox__fields">
        <Field :label="t('sandbox.field.plain')">
          <template #default="{ id, invalid }">
            <InputText :id="id" v-model="folder" :invalid="invalid" fluid />
          </template>
        </Field>
        <Field :label="t('sandbox.field.withHelp')" :help="t('sandbox.field.help')">
          <template #default="{ id, invalid }">
            <InputNumber
              :input-id="id"
              :model-value="22"
              :locale="locale"
              :invalid="invalid"
              fluid
            />
          </template>
        </Field>
        <Field :label="t('sandbox.field.error')" :issues="errorIssues">
          <template #default="{ id, invalid }">
            <Select v-model="encoder" :label-id="id" :options="encoders" :invalid="invalid" fluid />
          </template>
        </Field>
        <Field :label="t('sandbox.field.warning')" :issues="warningIssues">
          <template #default="{ id, invalid }">
            <InputNumber
              v-model="bitrate"
              :input-id="id"
              :locale="locale"
              :invalid="invalid"
              fluid
            />
          </template>
        </Field>
        <Field :label="t('sandbox.field.info')" :issues="infoIssues">
          <template #default="{ id }">
            <InputText :id="id" model-value="23.976" fluid />
          </template>
        </Field>
        <Field :label="t('sandbox.field.toggle')" :issues="warningIssues">
          <template #default="{ id }">
            <ToggleSwitch v-model="toggle" :input-id="id" />
          </template>
        </Field>
        <Field :label="t('sandbox.field.overridden')" overridden>
          <template #default="{ id }">
            <InputText :id="id" model-value="mkv" fluid />
          </template>
        </Field>
        <Field :label="t('sandbox.field.fromStore')" :path="STORE_PATH">
          <template #default="{ id, invalid }">
            <InputText :id="id" model-value="veryslow" :invalid="invalid" fluid />
          </template>
        </Field>
        <Field :label="t('sandbox.field.stacked')" stacked :issues="errorIssues">
          <template #default="{ id, invalid }">
            <InputText :id="id" :invalid="invalid" fluid />
          </template>
        </Field>
      </div>
      <div>
        <Button
          :label="t('sandbox.field.reveal')"
          severity="secondary"
          data-testid="reveal"
          @click="ui.reveal(STORE_PATH)"
        />
      </div>
    </Section>

    <Section v-model:collapsed="collapsed" :title="t('sandbox.section.collapsible')" collapsible>
      <template #actions>
        <Button :label="t('sandbox.section.action')" size="small" text />
      </template>
      <p>{{ t('sandbox.section.body') }}</p>
    </Section>

    <Section :title="t('sandbox.card.title')">
      <div class="sandbox__cards">
        <Card :title="t('sandbox.card.titled')">
          <p>{{ t('sandbox.card.body') }}</p>
        </Card>
        <Card>
          <template #header>
            <strong>{{ t('sandbox.card.custom') }}</strong>
          </template>
          <template #actions>
            <Button :label="t('sandbox.section.action')" size="small" text />
          </template>
          <p>{{ t('sandbox.card.body') }}</p>
        </Card>
        <Card>
          <p>{{ t('sandbox.card.body') }}</p>
        </Card>
      </div>
    </Section>

    <Section :title="t('sandbox.role.title')">
      <div v-for="row in evidenceRows" :key="row.evidence" class="sandbox__row">
        <span class="sandbox__row-label">{{ row.label }}</span>
        <RoleBadge
          v-for="role in ROLES"
          :key="role"
          :role="{ role, evidence: row.evidence, detail: row.detail }"
        />
        <RoleBadge :role="{ role: 'description', evidence: row.evidence }" kind="subtitle" />
      </div>
    </Section>

    <Section :title="t('sandbox.codec.title')">
      <div class="sandbox__row">
        <CodecLabel v-for="(stream, index) in CODECS" :key="index" :stream="stream" />
      </div>
    </Section>

    <Section :title="t('sandbox.language.title')">
      <div class="sandbox__row">
        <LanguageChip v-for="tag in LANGUAGE_TAGS" :key="tag ?? 'none'" :tag="tag" />
      </div>
    </Section>

    <Section :title="t('sandbox.status.title')">
      <div class="sandbox__row">
        <StatusDot v-for="tone in TONES" :key="tone" :tone="tone" :label="toneLabel[tone]" />
      </div>
      <div class="sandbox__row">
        <StatusDot
          v-for="tone in TONES"
          :key="tone"
          :tone="tone"
          :label="toneLabel[tone]"
          show-label
        />
      </div>
    </Section>

    <Section :title="t('sandbox.keyValue.title')">
      <dl class="rf-kv-list">
        <KeyValue :label="t('sandbox.keyValue.duration')" value="1:42:17" />
        <KeyValue :label="t('sandbox.keyValue.size')" :value="4096" />
        <KeyValue :label="t('sandbox.keyValue.missing')" :value="null" />
        <KeyValue :label="t('sandbox.keyValue.slot')">
          <StatusDot tone="ok" :label="t('sandbox.status.ok')" show-label />
        </KeyValue>
      </dl>
    </Section>

    <Section :title="t('sandbox.issues.title')">
      <IssueList :issues="listIssues" />
      <h3>{{ t('sandbox.issues.compact') }}</h3>
      <IssueList :issues="listIssues" compact />
      <h3>{{ t('sandbox.issues.empty') }}</h3>
      <IssueList :issues="[]" />
    </Section>

    <Section :title="t('sandbox.naming.title')" data-testid="naming-sandbox">
      <p>{{ t('sandbox.naming.intro') }}</p>
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
  max-width: 72rem;
  margin: 0 auto;
  padding: var(--rf-space-5);
}

.sandbox__header h1 {
  margin: 0 0 var(--rf-space-2);
  font-size: var(--rf-font-size-2xl);
}

.sandbox__header p {
  margin: 0 0 var(--rf-space-4);
  color: var(--rf-color-text-muted);
}

.sandbox__switches {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-5);
}

.sandbox__in-effect {
  align-self: end;
}

.sandbox__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.sandbox__row-label {
  width: 9rem;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.sandbox__fields {
  display: grid;
  gap: var(--rf-space-4);
  max-width: 40rem;
  padding-left: var(--rf-space-3);
}

.sandbox__cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
  gap: var(--rf-space-4);
}

.sandbox__naming {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 30rem), 1fr));
  gap: var(--rf-space-4);
  align-items: start;
}

.sandbox__swatch {
  padding: var(--rf-space-1) var(--rf-space-3);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
}

.sandbox__swatch--muted {
  color: var(--rf-color-text-muted);
}

.sandbox__swatch--primary {
  border-color: var(--rf-color-primary);
  background: var(--rf-color-primary);
  color: var(--rf-color-on-primary);
}

.sandbox__type {
  margin: 0;
}

.sandbox__type--xl {
  font-size: var(--rf-font-size-xl);
}

.sandbox__type--md {
  font-size: var(--rf-font-size-md);
}

.sandbox__type--sm {
  font-size: var(--rf-font-size-sm);
}
</style>
