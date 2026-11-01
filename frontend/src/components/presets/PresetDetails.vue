<script setup lang="ts">
import { Copy, Download, Lock, Pencil, Play, RefreshCw, Star, Trash2 } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Preset, Schemas } from '@/api/types'
import KeyValue from '@/components/base/KeyValue.vue'
import Section from '@/components/base/Section.vue'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { useSystemStore } from '@/stores/system'

import PresetNaming from './PresetNaming.vue'

/** One preset: what its template does in short, its naming, and what can be done with it. */
const props = defineProps<{
  preset: Preset
  isDefault: boolean
  /** A job is open: the preset can be applied to it. */
  canApply: boolean
  /** The open job's settings can be saved into a user preset. */
  canUpdate: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  apply: []
  duplicate: []
  rename: []
  update: []
  remove: []
  makeDefault: []
  export: []
}>()

const { t } = useI18n()
const system = useSystemStore()

type CodecRule = Schemas['AudioCodecRule']
type Selection = Schemas['TrackSelection']

const container = computed(() => {
  const id = props.preset.output?.container
  if (id === undefined) return null
  return system.definitions?.containers?.[id]?.label ?? id.toUpperCase()
})

const video = computed(() => {
  const settings = props.preset.video
  if (settings === undefined) return null
  if (settings.passthrough) return t('presets.details.videoCopy')
  const encoder = system.definitions?.video_encoders?.[settings.encoder]
  const name = encoder?.label ?? settings.encoder
  const control = settings.rate_control
  if (control === undefined) return name
  if (control.mode === 'bitrate') {
    return t('presets.details.videoBitrate', { encoder: name, kbps: control.kbps })
  }
  const scale = encoder?.rate_control?.quality?.label ?? ''
  return t('presets.details.videoQuality', {
    encoder: name,
    quality: `${scale} ${control.value}`.trim(),
  })
})

const size = computed(() => {
  const given = props.preset.dimensions?.size
  if (given === undefined) return null
  switch (given.mode) {
    case 'source':
      return t('presets.details.sizeSource')
    case 'fit':
      return t('presets.details.sizeFit', { width: given.width, height: given.height })
    case 'width':
      return t('presets.details.sizeWidth', { width: given.width })
    case 'height':
      return t('presets.details.sizeHeight', { height: given.height })
  }
  return null
})

function tracks(selection: Selection | undefined): string {
  switch (selection?.tracks_per_language) {
    case 'first':
      return t('presets.details.tracksFirst')
    case 'all':
      return t('presets.details.tracksAll')
    case 'none':
      return t('presets.details.tracksNone')
  }
  return ''
}

function languages(selection: Selection | undefined): string {
  const list = selection?.languages
  return list === null || list === undefined
    ? t('presets.details.languagesSettings')
    : list.join(', ')
}

function selectionWords(selection: Selection | undefined): string {
  return [tracks(selection), languages(selection)].filter((part) => part !== '').join(' · ')
}

function codecRule(rule: CodecRule): string {
  const codec =
    system.definitions?.audio_encoders?.[rule.codec]?.label ??
    system.definitions?.passthru_codecs?.[rule.codec]?.label ??
    rule.codec
  const mixdown = system.definitions?.mixdowns?.[rule.mixdown]?.label ?? rule.mixdown
  const parts = [codec, mixdown]
  if (rule.max_bitrate !== null && rule.max_bitrate !== undefined) {
    parts.push(t('presets.details.kbps', { kbps: rule.max_bitrate }))
  }
  return parts.join(' · ')
}

const audio = computed(() => {
  const defaults = props.preset.audio_defaults
  if (defaults === undefined) return null
  const rules = defaults.codec_rules?.map(codecRule) ?? []
  const passthru = defaults.passthru?.allowed ?? []
  return {
    selection: selectionWords(defaults.selection),
    rules: rules.length > 0 ? rules.join('; ') : t('presets.details.noRules'),
    passthru: passthru.length > 0 ? passthru.join(', ') : null,
  }
})

const subtitles = computed(() => {
  const defaults = props.preset.subtitle_defaults
  if (defaults === undefined) return null
  let burnIn = ''
  switch (defaults.burn_in) {
    case 'none':
      burnIn = t('presets.details.burnNone')
      break
    case 'foreign_audio':
      burnIn = t('presets.details.burnForeign')
      break
    case 'first':
      burnIn = t('presets.details.burnFirst')
      break
    case 'foreign_audio_then_first':
      burnIn = t('presets.details.burnForeignThenFirst')
      break
  }
  return {
    selection: selectionWords(defaults.selection),
    burnIn,
  }
})
</script>

<template>
  <article class="preset-details" :data-preset="preset.id">
    <header class="preset-details__header">
      <div class="preset-details__title">
        <h2 class="preset-details__name">{{ preset.name }}</h2>
        <span v-if="preset.built_in" class="preset-details__badge" data-badge="built-in">
          <Lock :size="14" aria-hidden="true" />
          {{ t('presets.details.locked') }}
        </span>
        <span v-if="isDefault" class="preset-details__badge preset-details__badge--default">
          <Star :size="14" aria-hidden="true" />
          {{ t('presets.default') }}
        </span>
      </div>
      <p class="preset-details__description">
        {{ preset.description || t('presets.details.noDescription') }}
      </p>
      <div class="preset-details__actions" role="group" :aria-label="t('presets.details.actions')">
        <FocusSafeButton
          size="small"
          class="preset-details__apply"
          :label="t('presets.details.apply')"
          :disabled="!canApply || busy"
          @click="emit('apply')"
        >
          <template #icon><Play :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
        <FocusSafeButton
          size="small"
          severity="secondary"
          class="preset-details__duplicate"
          :label="t('presets.details.duplicate')"
          :disabled="busy"
          @click="emit('duplicate')"
        >
          <template #icon><Copy :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
        <template v-if="!preset.built_in">
          <FocusSafeButton
            size="small"
            severity="secondary"
            class="preset-details__rename"
            :label="t('presets.details.rename')"
            :disabled="busy"
            @click="emit('rename')"
          >
            <template #icon><Pencil :size="16" aria-hidden="true" /></template>
          </FocusSafeButton>
          <FocusSafeButton
            v-tooltip.bottom="canUpdate ? undefined : t('presets.details.updateNoJob')"
            size="small"
            severity="secondary"
            class="preset-details__update"
            :label="t('presets.details.update')"
            :disabled="!canUpdate || busy"
            @click="emit('update')"
          >
            <template #icon><RefreshCw :size="16" aria-hidden="true" /></template>
          </FocusSafeButton>
        </template>
        <FocusSafeButton
          size="small"
          severity="secondary"
          class="preset-details__default"
          :label="t('presets.details.makeDefault')"
          :disabled="isDefault || busy"
          :aria-pressed="isDefault"
          @click="emit('makeDefault')"
        >
          <template #icon><Star :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
        <FocusSafeButton
          size="small"
          severity="secondary"
          class="preset-details__export"
          :label="t('presets.details.export')"
          :disabled="busy"
          @click="emit('export')"
        >
          <template #icon><Download :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
        <FocusSafeButton
          v-if="!preset.built_in"
          size="small"
          severity="danger"
          outlined
          class="preset-details__delete"
          :label="t('presets.details.delete')"
          :disabled="busy"
          @click="emit('remove')"
        >
          <template #icon><Trash2 :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
      </div>
      <p v-if="preset.built_in" class="preset-details__hint">
        {{ t('presets.details.lockedHint') }}
      </p>
    </header>

    <Section :title="t('presets.details.settings')">
      <dl class="rf-kv-list preset-details__summary">
        <KeyValue :label="t('presets.details.category')" :value="preset.category" />
        <KeyValue :label="t('presets.details.container')" :value="container" />
        <KeyValue :label="t('presets.details.video')" :value="video" />
        <KeyValue :label="t('presets.details.size')" :value="size" />
        <template v-if="audio">
          <KeyValue :label="t('presets.details.audioTracks')" :value="audio.selection" />
          <KeyValue :label="t('presets.details.audioCodecs')" :value="audio.rules" />
          <KeyValue
            v-if="audio.passthru"
            :label="t('presets.details.passthru')"
            :value="audio.passthru"
          />
        </template>
        <template v-if="subtitles">
          <KeyValue :label="t('presets.details.subtitleTracks')" :value="subtitles.selection" />
          <KeyValue :label="t('presets.details.burnIn')" :value="subtitles.burnIn" />
        </template>
      </dl>
    </Section>

    <Section :title="t('presets.details.naming')">
      <PresetNaming :preset="preset" />
    </Section>
  </article>
</template>

<style scoped>
.preset-details {
  display: grid;
  gap: var(--rf-space-4);
  align-content: start;
}

.preset-details__header {
  display: grid;
  gap: var(--rf-space-2);
}

.preset-details__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.preset-details__name {
  margin: 0;
  font-size: var(--rf-font-size-xl);
}

.preset-details__badge {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-pill);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.preset-details__badge--default {
  border-color: var(--p-status-warn-border-color);
  color: var(--p-status-warn-color);
}

.preset-details__description,
.preset-details__hint {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.preset-details__hint {
  font-size: var(--rf-font-size-sm);
}

.preset-details__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}
</style>
