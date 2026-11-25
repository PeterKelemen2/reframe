<script setup lang="ts">
import { ChevronRight, Wand2 } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Menu from 'primevue/menu'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type {
  AudioOutputTrack,
  Fix,
  SubtitleOutputTrack,
  TrackMetadata,
  ValidationIssue,
} from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useLanguageColor } from '@/components/base/languageColor'
import { findLanguage } from '@/components/base/languages'
import type { Container } from '@/components/language/catalog'
import LanguagePicker from '@/components/language/LanguagePicker.vue'
import { useJobSource } from '@/components/summary/useJobSource'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { inspected, useSubtitleFormatName } from './external'
import {
  audioNameValues,
  externalOf,
  type Flag,
  FLAGS,
  type MetadataChanges,
  metadataOps,
  metadataPaths,
  metadataPlace,
  NAME_TEMPLATES,
  NAME_VARIABLES,
  nameSuggestions,
  otherNameValues,
} from './metadata'
import { canCopy, containerDef } from './ops'

/**
 * The metadata block of one output track: language, name and flags. Each change is one undo
 * step.
 */
const props = defineProps<{
  list: 'video' | 'audio' | 'subtitles'
  /** The output track's place in its list; not used for `video`. */
  index?: number
  disabled?: boolean
  /** Folded behind a summary line (a track row); it opens when one of its fields has an issue. */
  collapsible?: boolean
}>()

const { t, locale } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()
const validation = useValidationStore()
const ui = useUiStore()
const { source } = useJobSource()
const formatName = useSubtitleFormatName()

const id = useId()
const nameMenu = useTemplateRef<InstanceType<typeof Menu>>('nameMenu')

const place = computed(() => metadataPlace(props.list, props.index))
const metadata = computed(() => editor.get(place.value.pointer) as TrackMetadata | undefined)

const audioTrack = computed(() =>
  props.list === 'audio' ? editor.job?.audio?.[props.index ?? 0] : undefined,
)
const subtitleTrack = computed(() =>
  props.list === 'subtitles' ? editor.job?.subtitles?.[props.index ?? 0] : undefined,
)
const external = computed(() => externalOf(subtitleTrack.value))

const stream = computed(() => {
  if (props.list === 'video') return source.value?.video?.[0]
  if (props.list === 'audio') {
    const wanted = audioTrack.value?.source_stream
    return source.value?.audio?.find((candidate) => candidate.index === wanted)
  }
  const wanted = subtitleTrack.value?.source
  return source.value?.subtitles?.find((candidate) => candidate.index === wanted)
})

const containerId = computed(() => editor.job?.output?.container)
const container = computed<Container | undefined>(() => {
  const value = containerId.value
  return value === 'mkv' || value === 'mp4' || value === 'webm' ? value : undefined
})

/** The language and title that `null` keeps: the source track's, or the external file's own. */
const sourceLanguage = computed<string | null>(() => {
  if (external.value) return external.value.language ?? null
  return stream.value?.language_ietf || stream.value?.language || null
})
const sourceTitle = computed<string | null>(() =>
  external.value ? (external.value.name ?? null) : (stream.value?.title ?? null),
)

function languageName(tag: string | null): string | null {
  if (!tag) return null
  return findLanguage(system.languages, tag)?.english_name ?? tag
}

const noneLabel = computed(() => {
  // An external file has no language of its own beyond what the user sets here.
  if (external.value) return t('tracks.metadata.fileLanguageUnset')
  const name = languageName(sourceLanguage.value)
  return name
    ? t('tracks.metadata.keepLanguageOf', { language: name })
    : t('tracks.metadata.keepLanguage')
})

const nameHelp = computed(() =>
  t('tracks.metadata.nameHelp', {
    example: '{lang_name} {channels} {codec}',
    result: 'Japanese 5.1 Opus',
    variables: NAME_VARIABLES.map((variable) => `{${variable}}`).join(' '),
    open: '{{',
    close: '}}',
  }),
)

const namePlaceholder = computed(() => {
  if (metadata.value?.name === '') return t('tracks.metadata.nameNone')
  return sourceTitle.value
    ? t('tracks.metadata.nameKeep', { title: sourceTitle.value })
    : t('tracks.metadata.nameKeepUntitled')
})

function apply(changes: MetadataChanges, coalesce?: string): void {
  const ops = metadataOps(place.value.pointer, metadata.value, changes, external.value)
  if (ops.length > 0) editor.patch(ops, coalesce ? { coalesce } : undefined)
}

function onLanguage(value: string | null): void {
  apply({ language: value })
}

function onName(value: string | undefined): void {
  apply({ name: value ?? '' }, `${place.value.path}.name`)
}

function onFlag(flag: Flag, value: boolean): void {
  apply({ [flag]: value })
}

/** The track's output codec, as a name template's `{codec}` gives it. */
function subtitleCodec(track: SubtitleOutputTrack | undefined): string | null {
  if (track === undefined) return null
  if (track.action === 'convert' && track.convert_to) return formatName(track.convert_to)
  const format = external.value ? inspected(external.value.path)?.format : stream.value?.codec
  return format ? formatName(format) : null
}

const copied = computed(() => {
  const track: AudioOutputTrack | undefined = audioTrack.value
  if (track?.action !== 'passthru') return false
  const def = containerDef(system.definitions, containerId.value)
  return canCopy(def?.audio, stream.value?.codec)
})

const suggestions = computed(() => {
  const languages = system.languages
  const language = metadata.value?.language ?? null
  if (props.list === 'audio' && audioTrack.value) {
    const audioStream = stream.value && 'channels' in stream.value ? stream.value : undefined
    const values = audioNameValues(audioTrack.value, audioStream, {
      languages,
      definitions: system.definitions,
      copied: copied.value,
    })
    return nameSuggestions(NAME_TEMPLATES.audio, values)
  }
  const values = otherNameValues(language || sourceLanguage.value, undefined, {
    languages,
    codec: props.list === 'subtitles' ? subtitleCodec(subtitleTrack.value) : null,
    title: sourceTitle.value,
  })
  return nameSuggestions(NAME_TEMPLATES.other, values)
})

const nameItems = computed(() => [
  {
    label: t('tracks.metadata.nameFromTrack'),
    items:
      suggestions.value.length > 0
        ? suggestions.value.map((suggestion) => ({
            label: suggestion.text,
            template: suggestion.template,
            command: () => apply({ name: suggestion.text }),
          }))
        : [{ label: t('tracks.metadata.nameNoSuggestions'), disabled: true }],
  },
  { separator: true },
  { label: t('tracks.metadata.nameKeepItem'), command: () => apply({ name: null }) },
  { label: t('tracks.metadata.nameNoneItem'), command: () => apply({ name: '' }) },
])

const fieldPaths = computed(() => metadataPaths(place.value.path))
const issues = computed<ValidationIssue[]>(() =>
  fieldPaths.value.flatMap((path) => validation.issuesFor(path)),
)
/** The block's issue fixes, one button each: a fix that several issues offer is shown once. */
const fixes = computed<Fix[]>(() => {
  const seen = new Set<string>()
  return issues.value
    .flatMap((issue) => issue.fixes ?? [])
    .filter((fix) => !seen.has(fix.label) && seen.add(fix.label))
})
const applying = ref(false)

async function applyFix(fix: Fix): Promise<void> {
  if (applying.value) return
  applying.value = true
  try {
    await editor.applyFix(fix)
  } finally {
    applying.value = false
  }
}

const open = ref(!props.collapsible)
const bodyId = `${id}-body`

watch(
  () => issues.value.length > 0,
  (has) => {
    if (has) open.value = true
  },
  { immediate: true },
)
// A link to one of the block's fields lands on a folded block: it opens first, so the field
// can take the focus.
watch(
  () => ui.revealed?.path,
  (path) => {
    if (path && fieldPaths.value.includes(path)) open.value = true
  },
  { immediate: true },
)

const colorOf = useLanguageColor()
const markColor = computed(() => colorOf(metadata.value?.language ?? sourceLanguage.value))

const summary = computed(() => {
  const value = metadata.value
  const language =
    languageName(value?.language ?? null) ??
    languageName(sourceLanguage.value) ??
    t('tracks.metadata.summaryUnd')
  const name = value?.name ?? sourceTitle.value
  const flags = FLAGS.filter((flag) => value?.[flag]).map((flag) =>
    t(`tracks.metadata.flag.${flag}`),
  )
  return t('tracks.metadata.summary', {
    language,
    name: name ? t('tracks.metadata.summaryName', { name }) : t('tracks.metadata.summaryNoName'),
    flags:
      flags.length > 0
        ? new Intl.ListFormat(locale.value, { style: 'short', type: 'unit' }).format(flags)
        : t('tracks.metadata.summaryNoFlags'),
  })
})
</script>

<template>
  <div
    class="track-metadata"
    :class="{ 'track-metadata--open': open, 'track-metadata--folding': collapsible }"
    :data-metadata="place.path"
  >
    <button
      v-if="collapsible"
      type="button"
      class="track-metadata__toggle"
      data-action="metadata-toggle"
      :aria-expanded="open"
      :aria-controls="bodyId"
      @click="open = !open"
    >
      <ChevronRight class="track-metadata__chevron" :size="16" aria-hidden="true" />
      <span class="track-metadata__title">{{ t('tracks.metadata.title') }}</span>
      <span
        class="track-metadata__mark"
        :class="{ 'is-pale': metadata?.commentary }"
        :style="{ background: markColor }"
        aria-hidden="true"
      />
      <span class="track-metadata__summary" data-role="summary">{{ summary }}</span>
    </button>
    <div v-show="open" :id="bodyId" class="track-metadata__body">
      <div class="track-metadata__text">
        <Field :label="t('tracks.metadata.language')" :path="`${place.path}.language`" stacked>
          <template #default="{ id: inputId, labelId, invalid }">
            <LanguagePicker
              :model-value="metadata?.language ?? null"
              :input-id="inputId"
              :labelledby="labelId"
              :invalid="invalid"
              :disabled="disabled"
              :container="container"
              :none-label="noneLabel"
              clearable
              @update:model-value="onLanguage"
            />
          </template>
        </Field>
        <Field
          :label="t('tracks.metadata.name')"
          :path="`${place.path}.name`"
          :help="nameHelp"
          stacked
        >
          <template #default="{ id: inputId, invalid, labelId }">
            <div class="track-metadata__name">
              <InputText
                :id="inputId"
                class="track-metadata__name-input"
                :model-value="metadata?.name ?? ''"
                :placeholder="namePlaceholder"
                :invalid="invalid"
                :disabled="disabled"
                data-role="name"
                @update:model-value="onName"
                @blur="editor.endCoalescing()"
              />
              <Button
                severity="secondary"
                outlined
                data-action="name-menu"
                :disabled="disabled"
                :aria-label="t('tracks.metadata.nameMenu')"
                :aria-describedby="labelId"
                aria-haspopup="menu"
                :aria-controls="`${id}-names`"
                @click="nameMenu?.toggle($event)"
              >
                <template #icon><Wand2 :size="16" aria-hidden="true" /></template>
              </Button>
              <Menu ref="nameMenu" :pt="{ root: { id: `${id}-names` } }" :model="nameItems" popup>
                <template #item="{ item, props: itemProps }">
                  <a v-bind="itemProps.action" class="track-metadata__name-item">
                    <span>{{ item.label }}</span>
                    <code v-if="item.template" class="track-metadata__template">
                      {{ item.template }}
                    </code>
                  </a>
                </template>
              </Menu>
            </div>
          </template>
        </Field>
      </div>
      <fieldset class="track-metadata__flags" :disabled="disabled">
        <legend class="track-metadata__legend">{{ t('tracks.metadata.flags') }}</legend>
        <Field
          v-for="flag in FLAGS"
          :key="flag"
          class="track-metadata__flag"
          :label="t(`tracks.metadata.flag.${flag}`)"
          :path="`${place.path}.${flag}`"
          stacked
        >
          <template #default="{ id: inputId, invalid }">
            <ToggleSwitch
              :input-id="inputId"
              :model-value="metadata?.[flag] === true"
              :invalid="invalid"
              :disabled="disabled"
              :data-flag="flag"
              @update:model-value="(value: boolean) => onFlag(flag, value)"
            />
          </template>
        </Field>
      </fieldset>
      <div v-if="fixes.length > 0" class="track-metadata__fixes" data-role="fixes">
        <Button
          v-for="fix in fixes"
          :key="fix.label"
          size="small"
          severity="secondary"
          outlined
          :label="fix.label"
          :disabled="applying || disabled"
          @click="applyFix(fix)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.track-metadata {
  display: grid;
  gap: var(--rf-space-2);
  min-width: 0;
}

.track-metadata__toggle {
  display: flex;
  align-items: baseline;
  gap: var(--rf-space-2);
  min-width: 0;
  margin: 0;
  padding: var(--rf-space-1) 0;
  border: 0;
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  text-align: start;
  cursor: pointer;
}

.track-metadata__chevron {
  flex: none;
  align-self: center;
  transition: transform 0.15s ease;
}

.track-metadata--open .track-metadata__chevron {
  transform: rotate(90deg);
}

@media (prefers-reduced-motion: reduce) {
  .track-metadata__chevron {
    transition: none;
  }
}

.track-metadata__title {
  flex: none;
  font-weight: var(--rf-font-weight-medium);
}

/* The language's colour, as the track lists and the programme strip draw it. */
.track-metadata__mark {
  flex: none;
  width: 0.25rem;
  height: 1rem;
  border-radius: 1px;
}

.track-metadata__mark.is-pale {
  opacity: var(--rf-lang-pale);
}

.track-metadata__summary {
  min-width: 0;
  overflow: hidden;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.track-metadata__body {
  display: grid;
  gap: var(--rf-space-3);
  min-width: 0;
}

.track-metadata--folding .track-metadata__body {
  padding-inline-start: var(--rf-space-5);
}

.track-metadata__text {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-3);
}

.track-metadata__text > * {
  flex: 1 1 16rem;
  min-width: 0;
}

.track-metadata__name {
  display: flex;
  gap: var(--rf-space-1);
}

.track-metadata__name-input {
  flex: 1;
  min-width: 0;
}

.track-metadata__name-item {
  display: grid;
  gap: 0.125rem;
}

.track-metadata__template {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.track-metadata__flags {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  align-items: start;
  gap: var(--rf-space-3);
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.track-metadata__legend {
  margin-bottom: var(--rf-space-2);
  padding: 0;
  font-weight: var(--rf-font-weight-medium);
}

.track-metadata__fixes {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1);
}
</style>
