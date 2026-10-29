<script setup lang="ts">
import Checkbox from 'primevue/checkbox'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SubtitleOutputTrack, SubtitleStream } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { streamLabel } from '@/components/media/streams'
import { fileName } from '@/components/shell/format'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'

import {
  canCopy,
  containerDef,
  sourceChangeOps,
  SUBTITLE_FORMATS,
  type SubtitleFormat,
  subtitleActionOps,
} from './ops'
import TrackRowFrame from './TrackRowFrame.vue'

const props = defineProps<{
  index: number
  count: number
  track: SubtitleOutputTrack
  /** The source's subtitle tracks; empty while the source is not known. */
  streams: readonly SubtitleStream[]
}>()

const emit = defineEmits<{ move: [to: number]; remove: [] }>()

const { t } = useI18n()
const editor = useEditorStore()
const system = useSystemStore()

const path = computed(() => `subtitles[${props.index}]`)
const base = computed(() => `/subtitles/${props.index}`)

const external = computed(() =>
  typeof props.track.source === 'object' ? props.track.source : null,
)
const stream = computed(() =>
  props.streams.find((candidate) => candidate.index === props.track.source),
)
const container = computed(() => containerDef(system.definitions, editor.job?.output?.container))
const bitmap = computed(() => stream.value?.subtitle_kind === 'bitmap')
const showForcedOnly = computed(() => props.track.action === 'burn' || props.track.forced_only)

/** The paths of the fields shown: an issue elsewhere in the track is listed under the row. */
const fieldPaths = computed(() => {
  const fields = ['source', 'action']
  if (props.track.action === 'convert') fields.push('convert_to')
  if (showForcedOnly.value) fields.push('forced_only')
  return fields.map((field) => `${path.value}.${field}`)
})

/** A copied text track the container cannot hold is converted on the way (MP4: mov_text). */
const convertedOnCopy = computed<string | null>(() => {
  const codec = stream.value?.codec
  if (props.track.action !== 'copy' || bitmap.value || !codec || !container.value) return null
  if (canCopy(container.value.subtitles, codec)) return null
  return container.value.text_subtitle_target ?? null
})

const sourceOptions = computed(() =>
  props.streams.map((candidate) => ({ value: candidate.index, label: streamLabel(candidate) })),
)

function onSource(index: number): void {
  const next = props.streams.find((candidate) => candidate.index === index)
  if (next && index !== props.track.source) {
    editor.patch(sourceChangeOps('subtitles', props.index, props.track, next))
  }
}

const actionOptions = computed(() => [
  { value: 'copy', label: t('tracks.output.copy'), disabled: false },
  { value: 'burn', label: t('tracks.output.burn'), disabled: false },
  { value: 'convert', label: t('tracks.output.convert'), disabled: bitmap.value },
])

function onAction(action: SubtitleOutputTrack['action'] | null): void {
  if (!action || action === props.track.action) return
  editor.patch(subtitleActionOps(props.index, props.track, action, container.value))
}

function formatLabel(format: SubtitleFormat): string {
  switch (format) {
    case 'srt':
      return t('tracks.output.formatSrt')
    case 'ass':
      return t('tracks.output.formatAss')
    case 'webvtt':
      return t('tracks.output.formatWebvtt')
    case 'mov_text':
      return t('tracks.output.formatMovText')
  }
  return format
}

const formatOptions = computed(() =>
  SUBTITLE_FORMATS.map((format) => ({ value: format, label: formatLabel(format) })),
)
</script>

<template>
  <TrackRowFrame
    :path="path"
    :index="index"
    :count="count"
    :field-paths="fieldPaths"
    @move="(to) => emit('move', to)"
    @remove="emit('remove')"
  >
    <template #header>
      <Field :label="t('tracks.output.source')" :path="`${path}.source`" stacked>
        <template #default="{ id, labelId, invalid }">
          <span v-if="external" :id="id" class="track-field__external">
            {{ t('tracks.output.externalFile', { name: fileName(external.path) }) }}
          </span>
          <Select
            v-else
            :input-id="id"
            :ariaLabelledby="labelId"
            class="track-field__control"
            :model-value="stream ? track.source : null"
            :options="sourceOptions"
            option-label="label"
            option-value="value"
            :placeholder="t('tracks.output.missingStream', { index: track.source })"
            :disabled="streams.length === 0"
            :invalid="invalid"
            @update:model-value="onSource"
          />
        </template>
      </Field>
    </template>
    <div class="track-fields">
      <Field
        class="track-field--fit"
        :label="t('tracks.output.action')"
        :path="`${path}.action`"
        stacked
      >
        <template #default="{ id, invalid, labelId }">
          <SelectButton
            :pt="{ root: { id } }"
            :model-value="track.action"
            :options="actionOptions"
            option-label="label"
            option-value="value"
            option-disabled="disabled"
            :allow-empty="false"
            :invalid="invalid"
            :ariaLabelledby="labelId"
            @update:model-value="onAction"
          />
        </template>
      </Field>
      <Field
        v-if="track.action === 'convert'"
        :label="t('tracks.output.format')"
        :path="`${path}.convert_to`"
        stacked
      >
        <template #default="{ id, labelId, invalid }">
          <Select
            :input-id="id"
            :ariaLabelledby="labelId"
            class="track-field__control"
            :model-value="track.convert_to"
            :options="formatOptions"
            option-label="label"
            option-value="value"
            :placeholder="t('tracks.output.chooseFormat')"
            :invalid="invalid"
            @update:model-value="(value: SubtitleFormat) => editor.set(`${base}/convert_to`, value)"
          />
        </template>
      </Field>
      <Field
        v-if="showForcedOnly"
        :label="t('tracks.output.forcedOnly')"
        :path="`${path}.forced_only`"
        :help="t('tracks.output.forcedOnlyHelp')"
        stacked
      >
        <template #default="{ id, invalid }">
          <Checkbox
            :input-id="id"
            binary
            :model-value="track.forced_only"
            :invalid="invalid"
            @update:model-value="(value: boolean) => editor.set(`${base}/forced_only`, value)"
          />
        </template>
      </Field>
    </div>
    <p v-if="convertedOnCopy" class="track-fields__note" data-note="converted">
      {{
        t('tracks.output.convertedOnCopy', {
          container: container?.label ?? '',
          codec: stream?.display_codec || stream?.codec || '',
          format: convertedOnCopy,
        })
      }}
    </p>
  </TrackRowFrame>
</template>

<style scoped>
.track-fields {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-3);
  align-items: flex-start;
}

.track-fields > * {
  flex: 1 1 11rem;
  min-width: 0;
}

.track-fields > .track-field--fit {
  flex: 0 1 auto;
}

/* A label with a help button is taller: every label gets its height, so the controls line up. */
.track-fields :deep(.rf-field__label) {
  min-height: 1.75rem;
}

.track-fields__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.track-field__control {
  width: 100%;
}

.track-field__external {
  display: inline-block;
  padding: var(--rf-space-2) 0;
  overflow-wrap: anywhere;
}
</style>
