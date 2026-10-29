<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Severity } from '@/api/types'
import Card from '@/components/base/Card.vue'
import CodecLabel from '@/components/base/CodecLabel.vue'
import LanguageChip from '@/components/base/LanguageChip.vue'
import RoleBadge from '@/components/base/RoleBadge.vue'
import { SEVERITY_ICON, useSeverityLabel } from '@/components/base/severity'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'
import { useValidationStore } from '@/stores/validation'

import { audioChips, type Flag, subtitleChips } from './tracks'
import { useJobSource } from './useJobSource'

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()
const system = useSystemStore()
const ui = useUiStore()
const validation = useValidationStore()
const { source } = useJobSource()

/** The most severe issue of the track or one of its fields marks its chip. */
function severityOf(path: string): Severity | null {
  return validation.issuesFor(path, { nested: true })[0]?.severity ?? null
}

const audio = computed(() =>
  editor.job === null
    ? []
    : audioChips(editor.job, source.value, system.definitions).map((chip) =>
        Object.assign(chip, { severity: severityOf(chip.path) }),
      ),
)
const subtitles = computed(() =>
  editor.job === null
    ? []
    : subtitleChips(editor.job, source.value).map((chip) =>
        Object.assign(chip, { severity: severityOf(chip.path) }),
      ),
)

function flagLabel(flag: Flag): string {
  switch (flag) {
    case 'default':
      return t('summary.tracks.flag.default')
    case 'forced':
      return t('summary.tracks.flag.forced')
    case 'commentary':
      return t('summary.tracks.flag.commentary')
    case 'hearing_impaired':
      return t('summary.tracks.flag.hearingImpaired')
    case 'visual_impaired':
      return t('summary.tracks.flag.visualImpaired')
    case 'original':
      return t('summary.tracks.flag.original')
  }
  return flag
}

function action(chip: (typeof subtitles.value)[number]): string | null {
  switch (chip.action) {
    case 'burn':
      return t('summary.tracks.burn')
    case 'convert':
      return chip.convertTo === null
        ? null
        : t('summary.tracks.convert', { format: chip.convertTo })
    default:
      return null
  }
}
</script>

<template>
  <Card
    class="summary-card summary-card--wide summary-tracks"
    :title="t('summary.tracks.title')"
    data-card="tracks"
  >
    <div class="summary-tracks__body">
      <section class="summary-tracks__group" data-group="audio">
        <h4 class="summary-card__subtitle">{{ t('summary.tracks.audio', audio.length) }}</h4>
        <p v-if="audio.length === 0" class="summary-card__note">
          {{ t('summary.tracks.noAudio') }}
        </p>
        <ul v-else class="summary-tracks__list">
          <li v-for="(chip, index) in audio" :key="chip.path">
            <button
              type="button"
              class="summary-track"
              :class="chip.severity && `summary-track--${chip.severity}`"
              :data-path="chip.path"
              @click="ui.reveal(chip.path)"
            >
              <span class="summary-track__index">{{ index + 1 }}</span>
              <LanguageChip :tag="chip.language" />
              <span class="summary-track__codec">
                <template v-if="chip.passthru">
                  <CodecLabel v-if="chip.stream" :stream="chip.stream" />
                  <span>{{ t('summary.tracks.passthru') }}</span>
                </template>
                <strong v-else>{{ chip.encoder }}</strong>
              </span>
              <span v-if="chip.layout" class="summary-track__layout">{{ chip.layout }}</span>
              <span v-if="chip.name" class="summary-track__name">{{ chip.name }}</span>
              <RoleBadge v-for="role in chip.roles" :key="role.role" :role="role" />
              <span v-for="flag in chip.flags" :key="flag" class="summary-track__flag">
                {{ flagLabel(flag) }}
              </span>
              <template v-if="chip.severity">
                <component
                  :is="SEVERITY_ICON[chip.severity]"
                  class="summary-track__issue"
                  :size="16"
                  aria-hidden="true"
                />
                <span class="rf-sr-only">{{ severityLabel(chip.severity) }}</span>
              </template>
            </button>
          </li>
        </ul>
      </section>
      <section class="summary-tracks__group" data-group="subtitles">
        <h4 class="summary-card__subtitle">
          {{ t('summary.tracks.subtitles', subtitles.length) }}
        </h4>
        <p v-if="subtitles.length === 0" class="summary-card__note">
          {{ t('summary.tracks.noSubtitles') }}
        </p>
        <ul v-else class="summary-tracks__list">
          <li v-for="(chip, index) in subtitles" :key="chip.path">
            <button
              type="button"
              class="summary-track"
              :class="chip.severity && `summary-track--${chip.severity}`"
              :data-path="chip.path"
              @click="ui.reveal(chip.path)"
            >
              <span class="summary-track__index">{{ index + 1 }}</span>
              <LanguageChip :tag="chip.language" />
              <span class="summary-track__codec">
                <CodecLabel v-if="chip.stream" :stream="chip.stream" />
                <strong v-else-if="chip.external">{{ chip.external }}</strong>
                <span v-if="action(chip)">{{ action(chip) }}</span>
              </span>
              <span v-if="chip.name" class="summary-track__name">{{ chip.name }}</span>
              <RoleBadge v-for="role in chip.roles" :key="role.role" :role="role" kind="subtitle" />
              <span v-for="flag in chip.flags" :key="flag" class="summary-track__flag">
                {{ flagLabel(flag) }}
              </span>
              <template v-if="chip.severity">
                <component
                  :is="SEVERITY_ICON[chip.severity]"
                  class="summary-track__issue"
                  :size="16"
                  aria-hidden="true"
                />
                <span class="rf-sr-only">{{ severityLabel(chip.severity) }}</span>
              </template>
            </button>
          </li>
        </ul>
      </section>
    </div>
  </Card>
</template>

<style scoped>
.summary-tracks__body {
  display: grid;
  gap: var(--rf-space-4);
}

.summary-tracks__group {
  display: grid;
  gap: var(--rf-space-2);
}

.summary-tracks__list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.summary-track {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-1) var(--rf-space-2);
  max-width: 100%;
  padding: var(--rf-space-1) var(--rf-space-3) var(--rf-space-1) var(--rf-space-1);
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-pill);
  background: var(--rf-color-surface);
  color: var(--rf-color-text);
  font: inherit;
  font-size: var(--rf-font-size-sm);
  text-align: start;
  cursor: pointer;
}

.summary-track:hover {
  background: var(--rf-color-surface-hover);
}

.summary-track:focus-visible {
  outline: 2px solid var(--rf-color-primary);
  outline-offset: 2px;
}

.summary-track--error {
  border-color: var(--p-status-error-border-color);
}

.summary-track--warning {
  border-color: var(--p-status-warn-border-color);
}

.summary-track--error .summary-track__issue {
  color: var(--p-status-error-color);
}

.summary-track--warning .summary-track__issue {
  color: var(--p-status-warn-color);
}

.summary-track--info .summary-track__issue {
  color: var(--p-status-info-color);
}

.summary-track__index {
  display: inline-grid;
  place-items: center;
  min-width: 1.5rem;
  height: 1.5rem;
  border-radius: 50%;
  background: var(--p-status-off-background);
  font-size: var(--rf-font-size-xs);
  font-weight: var(--rf-font-weight-bold);
}

.summary-track__codec {
  display: inline-flex;
  gap: var(--rf-space-1);
  align-items: center;
}

.summary-track__name {
  color: var(--rf-color-text-muted);
}

.summary-track__flag {
  padding: 0 var(--rf-space-2);
  border-radius: var(--rf-radius-sm);
  background: var(--p-status-info-background);
  color: var(--p-status-info-color);
  font-size: var(--rf-font-size-xs);
  line-height: 1.5rem;
}
</style>
