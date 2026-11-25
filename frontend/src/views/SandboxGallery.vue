<script setup lang="ts">
import { Play, Trash2 } from '@lucide/vue'
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import InputText from 'primevue/inputtext'
import ProgressBar from 'primevue/progressbar'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { TrackRoleInfo, ValidationIssue } from '@/api/types'
import Card from '@/components/base/Card.vue'
import CodecLabel from '@/components/base/CodecLabel.vue'
import Field from '@/components/base/Field.vue'
import IssueList from '@/components/base/IssueList.vue'
import KeyValue from '@/components/base/KeyValue.vue'
import LanguageChip from '@/components/base/LanguageChip.vue'
import { LANGUAGE_SLOTS, type LanguageSlot, languageSlot } from '@/components/base/languageColor'
import RoleBadge from '@/components/base/RoleBadge.vue'
import Section from '@/components/base/Section.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import type { CodecInfo, StatusTone } from '@/components/base/types'
import { useSettingsStore } from '@/stores/settings'
import { useSystemStore } from '@/stores/system'

/** Every base component in one colour scheme; the sandbox shows it once per scheme. */
const props = defineProps<{
  /** The validation path whose issue comes from the store. */
  storePath: string
}>()

const { t, locale } = useI18n()
const system = useSystemStore()
const settings = useSettingsStore()

function issue(severity: ValidationIssue['severity'], message: string, path = ''): ValidationIssue {
  return { severity, code: `sandbox.${severity}`, path, message, fixes: [] }
}

const errorIssues = computed(() => [issue('error', t('sandbox.field.errorMessage'))])
const warningIssues = computed(() => [issue('warning', t('sandbox.field.warningMessage'))])
const infoIssues = computed(() => [issue('info', t('sandbox.field.infoMessage'))])

const listIssues = computed<ValidationIssue[]>(() => [
  issue('info', t('sandbox.field.infoMessage'), 'video.frame_rate'),
  issue('warning', t('sandbox.field.warningMessage'), 'audio[1].bitrate'),
  {
    ...issue('error', t('sandbox.field.errorMessage'), props.storePath),
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
const container = ref('mkv')
const containers = ['mkv', 'mp4', 'webm']
/** The tag of an undetermined language. */
const UND = 'und'

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

/** Tried after the server's languages when a slot has none yet: the sandbox may run without one. */
const MORE_TAGS = 'fra spa ita rus kor zho pol ces swe nld tur ara heb hin tha vie fin nor dan ell'
  .split(' ')
  .concat('ukr ron bul hrv srp slk slv est lav lit ind msa cat eus glg isl gle cym'.split(' '))

/** One language per colour slot, as the user's preferred languages give them out. */
const slotTags = computed(() => {
  const languages = settings.settings?.languages
  const preferred = [
    ...(languages?.preferred_audio ?? []),
    ...(languages?.preferred_subtitle ?? []),
    ...(languages?.favourites ?? []),
  ]
  const found = new Map<LanguageSlot, string>()
  for (const tag of [...preferred, ...system.languages.map((each) => each.tag), ...MORE_TAGS]) {
    const slot = languageSlot(tag, system.languages, preferred)
    if (!found.has(slot)) found.set(slot, tag)
    if (found.size >= LANGUAGE_SLOTS) break
  }
  return Array.from({ length: LANGUAGE_SLOTS }, (_, index) => ({
    slot: index + 1,
    tag: found.get(index + 1) ?? null,
  }))
})

const TONES: StatusTone[] = ['ok', 'busy', 'warn', 'error', 'off']
const toneLabel = computed<Record<StatusTone, string>>(() => ({
  ok: t('sandbox.status.ok'),
  busy: t('sandbox.status.busy'),
  warn: t('sandbox.status.warn'),
  error: t('sandbox.status.error'),
  off: t('sandbox.status.off'),
}))
</script>

<template>
  <div class="gallery">
    <Section :title="t('sandbox.tokens.title')">
      <div class="gallery__type">
        <p class="gallery__role gallery__role--title">{{ t('sandbox.type.title') }}</p>
        <p class="gallery__role gallery__role--heading">{{ t('sandbox.type.heading') }}</p>
        <p class="gallery__role gallery__role--subheading">{{ t('sandbox.type.subheading') }}</p>
        <p class="gallery__role">{{ t('sandbox.tokens.sample') }}</p>
        <p class="gallery__role gallery__role--label">{{ t('sandbox.type.label') }}</p>
        <p class="gallery__role gallery__role--mono rf-mono">{{ t('sandbox.type.mono') }}</p>
      </div>
      <div class="gallery__row">
        <span class="gallery__swatch">{{ t('sandbox.tokens.text') }}</span>
        <span class="gallery__swatch gallery__swatch--muted">{{ t('sandbox.tokens.muted') }}</span>
        <span class="gallery__swatch gallery__swatch--primary">{{
          t('sandbox.tokens.primary')
        }}</span>
        <span class="gallery__swatch gallery__swatch--booth">{{ t('sandbox.tokens.booth') }}</span>
      </div>
      <div class="gallery__row">
        <span
          v-for="tone in TONES"
          :key="tone"
          class="gallery__swatch"
          :style="{
            color: `var(--p-status-${tone}-color)`,
            background: `var(--p-status-${tone}-background)`,
            borderColor: `var(--p-status-${tone}-border-color)`,
          }"
          >{{ toneLabel[tone] }}</span
        >
      </div>
    </Section>

    <Section :title="t('sandbox.controls.title')">
      <div class="gallery__row">
        <Button :label="t('sandbox.controls.primary')">
          <template #icon><Play :size="16" aria-hidden="true" /></template>
        </Button>
        <Button :label="t('sandbox.controls.secondary')" severity="secondary" />
        <Button :label="t('sandbox.controls.outlined')" severity="secondary" outlined />
        <Button :label="t('sandbox.controls.text')" severity="secondary" text />
        <Button :label="t('sandbox.controls.danger')" severity="danger" outlined>
          <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
        </Button>
        <Button :label="t('sandbox.controls.disabled')" disabled />
      </div>
      <div class="gallery__row">
        <SelectButton
          v-model="container"
          :options="containers"
          :allow-empty="false"
          :pt="{ root: { 'aria-label': t('sandbox.field.overridden') } }"
        />
        <ToggleSwitch
          v-model="toggle"
          :pt="{ input: { 'aria-label': t('sandbox.field.toggle') } }"
        />
        <ProgressBar
          class="gallery__progress"
          :value="42"
          :show-value="false"
          :pt="{ root: { 'aria-label': t('sandbox.controls.progress') } }"
        />
      </div>
    </Section>

    <Section :title="t('sandbox.field.title')">
      <div class="gallery__fields">
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
        <Field :label="t('sandbox.field.fromStore')" :path="storePath">
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
    </Section>

    <Section v-model:collapsed="collapsed" :title="t('sandbox.section.collapsible')" collapsible>
      <template #actions>
        <Button :label="t('sandbox.section.action')" size="small" text />
      </template>
      <p class="gallery__text">{{ t('sandbox.section.body') }}</p>
    </Section>

    <Section :title="t('sandbox.card.title')">
      <div class="gallery__cards">
        <Card :title="t('sandbox.card.titled')">
          <p class="gallery__text">{{ t('sandbox.card.body') }}</p>
        </Card>
        <Card>
          <template #header>
            <strong>{{ t('sandbox.card.custom') }}</strong>
          </template>
          <template #actions>
            <Button :label="t('sandbox.section.action')" size="small" text />
          </template>
          <p class="gallery__text">{{ t('sandbox.card.body') }}</p>
        </Card>
      </div>
    </Section>

    <Section :title="t('sandbox.language.title')">
      <ul class="gallery__slots">
        <li v-for="{ slot, tag } in slotTags" :key="slot" :data-slot="slot">
          <span class="gallery__slot rf-mono">{{ slot }}</span>
          <LanguageChip v-if="tag !== null" :tag="tag" />
        </li>
        <li data-slot="und">
          <span class="gallery__slot rf-mono">{{ UND }}</span>
          <LanguageChip :tag="UND" />
        </li>
        <li data-slot="pale">
          <span class="gallery__slot">{{ t('sandbox.language.pale') }}</span>
          <LanguageChip :tag="slotTags[0]?.tag" pale />
        </li>
        <li data-slot="unknown">
          <span class="gallery__slot">{{ t('sandbox.language.unknown') }}</span>
          <LanguageChip tag="xyz" />
        </li>
      </ul>
    </Section>

    <Section :title="t('sandbox.role.title')">
      <div v-for="row in evidenceRows" :key="row.evidence" class="gallery__row">
        <span class="gallery__row-label">{{ row.label }}</span>
        <RoleBadge
          v-for="role in ROLES"
          :key="role"
          :role="{ role, evidence: row.evidence, detail: row.detail }"
        />
        <RoleBadge :role="{ role: 'description', evidence: row.evidence }" kind="subtitle" />
      </div>
    </Section>

    <Section :title="t('sandbox.codec.title')">
      <div class="gallery__row">
        <CodecLabel v-for="(stream, index) in CODECS" :key="index" :stream="stream" />
      </div>
    </Section>

    <Section :title="t('sandbox.status.title')">
      <div class="gallery__row">
        <StatusDot v-for="tone in TONES" :key="tone" :tone="tone" :label="toneLabel[tone]" />
      </div>
      <div class="gallery__row">
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
      <h3 class="gallery__subheading">{{ t('sandbox.issues.compact') }}</h3>
      <IssueList :issues="listIssues" compact />
      <h3 class="gallery__subheading">{{ t('sandbox.issues.empty') }}</h3>
      <IssueList :issues="[]" />
    </Section>
  </div>
</template>

<style scoped>
.gallery {
  display: grid;
  gap: var(--rf-space-6);
  min-width: 0;
}

.gallery__type {
  display: grid;
  gap: var(--rf-space-2);
}

.gallery__role {
  margin: 0;
  line-height: var(--rf-line-height-tight);
}

.gallery__role--title {
  font-size: var(--rf-text-title);
  font-weight: var(--rf-font-weight-bold);
}

.gallery__role--heading {
  font-size: var(--rf-text-heading);
  font-weight: var(--rf-font-weight-bold);
}

.gallery__role--subheading {
  font-size: var(--rf-text-subheading);
  font-weight: var(--rf-font-weight-bold);
}

.gallery__role--label {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-text-label);
  font-weight: var(--rf-font-weight-medium);
  letter-spacing: var(--rf-tracking-label);
  text-transform: uppercase;
}

.gallery__role--mono {
  font-size: var(--rf-font-size-sm);
}

.gallery__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-3);
}

.gallery__row-label {
  width: 9rem;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.gallery__text {
  margin: 0;
}

.gallery__subheading {
  margin: var(--rf-space-2) 0 0;
  font-size: var(--rf-text-subheading);
}

.gallery__fields {
  display: grid;
  gap: var(--rf-space-4);
}

.gallery__cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
  gap: var(--rf-space-4);
}

.gallery__progress {
  width: 10rem;
  height: 0.25rem;
}

.gallery__swatch {
  padding: var(--rf-space-1) var(--rf-space-3);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-color-surface);
}

.gallery__swatch--muted {
  color: var(--rf-color-text-muted);
}

.gallery__swatch--primary {
  border-color: var(--rf-color-primary);
  background: var(--rf-color-primary);
  color: var(--rf-color-on-primary);
}

.gallery__swatch--booth {
  background: var(--rf-color-booth);
}

.gallery__slots {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--rf-space-2) var(--rf-space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.gallery__slots li {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 0;
}

.gallery__slot {
  min-width: 2.5rem;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}
</style>
