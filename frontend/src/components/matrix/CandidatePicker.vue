<script setup lang="ts">
import { CircleOff, RotateCcw } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { AudioStream, MatrixColumn, SubtitleStream, TrackMatch } from '@/api/types'
import { useEditorStore } from '@/stores/editor'

import { trackText } from './matrix'

/** A cell's tracks to pick by hand in one file: any track of the kind, or no track. */
const props = defineProps<{
  sourceId: string
  label: string
  column: MatrixColumn
  match: TrackMatch
  tracks: (AudioStream | SubtitleStream)[]
  /** The file's override picks this rule's track already. */
  picked: boolean
}>()

const emit = defineEmits<{ done: [] }>()

const { t } = useI18n()
const editor = useEditorStore()

const kind = computed(() => props.match.kind)
const rule = computed(() => props.match.rule)

function pick(stream: number | null): void {
  editor.pickTrack(props.sourceId, kind.value, rule.value, stream)
  emit('done')
}

function reset(): void {
  editor.resetTrack(props.sourceId, kind.value, rule.value)
  emit('done')
}
</script>

<template>
  <div class="candidate-picker" :data-column="column.label">
    <p class="candidate-picker__title">
      {{ t('matrix.picker.title', { column: column.label, label }) }}
    </p>
    <p v-if="match.defaults" class="candidate-picker__defaults" data-role="defaults">
      {{
        match.kind === 'audio'
          ? t('matrix.picker.defaultsAudio')
          : t('matrix.picker.defaultsSubtitle')
      }}
    </p>
    <template v-else>
      <p v-if="tracks.length === 0" class="candidate-picker__none">
        {{ t('matrix.picker.noTracks') }}
      </p>
      <ul class="candidate-picker__list">
        <li v-for="(track, index) in tracks" :key="track.index">
          <button
            type="button"
            class="candidate-picker__option"
            :data-stream="track.index"
            :autofocus="index === 0 || undefined"
            @click="pick(track.index)"
          >
            <span dir="ltr">{{ trackText(track) }}</span>
            <span v-if="(match.streams ?? []).includes(track.index)" class="candidate-picker__tag">
              {{ t('matrix.picker.taken') }}
            </span>
            <span
              v-if="(match.candidates ?? []).includes(track.index)"
              class="candidate-picker__tag"
            >
              {{ t('matrix.picker.candidate') }}
            </span>
          </button>
        </li>
        <li>
          <button
            type="button"
            class="candidate-picker__option"
            data-stream="none"
            :autofocus="tracks.length === 0 || undefined"
            @click="pick(null)"
          >
            <CircleOff :size="14" aria-hidden="true" />
            {{ t('matrix.picker.noTrack') }}
          </button>
        </li>
        <li v-if="picked">
          <button type="button" class="candidate-picker__option" data-role="reset" @click="reset">
            <RotateCcw :size="14" aria-hidden="true" />
            {{ t('matrix.picker.reset') }}
          </button>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.candidate-picker {
  display: grid;
  gap: var(--rf-space-2);
  max-width: 32rem;
}

.candidate-picker p {
  margin: 0;
}

.candidate-picker__title {
  font-weight: var(--rf-font-weight-medium);
}

.candidate-picker__defaults,
.candidate-picker__none {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.candidate-picker__list {
  display: grid;
  gap: var(--rf-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.candidate-picker__option {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
  width: 100%;
  padding: var(--rf-space-1) var(--rf-space-2);
  border: 1px solid transparent;
  border-radius: var(--rf-radius-sm);
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.candidate-picker__option:hover {
  background: var(--rf-color-surface-hover);
}

.candidate-picker__tag {
  padding: 0 var(--rf-space-2);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-pill);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}
</style>
