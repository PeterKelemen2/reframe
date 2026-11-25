<script setup lang="ts">
import { ArrowRight } from '@lucide/vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Severity, TrackRoleInfo } from '@/api/types'
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
import { useTrackNames } from './useTrackNames'

const { t, n } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()
const system = useSystemStore()
const ui = useUiStore()
const validation = useValidationStore()
const { source } = useJobSource()
const { names } = useTrackNames()

/** The most severe issue of the track or one of its fields marks its row. */
function severityOf(path: string): Severity | null {
  return validation.issuesFor(path, { nested: true })[0]?.severity ?? null
}

const audio = computed(() =>
  editor.job === null
    ? []
    : audioChips(editor.job, source.value, system.definitions, names.value?.audio).map((chip) =>
        Object.assign(chip, { severity: severityOf(chip.path) }),
      ),
)
const subtitles = computed(() =>
  editor.job === null
    ? []
    : subtitleChips(editor.job, source.value, names.value?.subtitles, system.definitions).map(
        (chip) => Object.assign(chip, { severity: severityOf(chip.path) }),
      ),
)

const videoStream = computed(() => source.value?.video?.[0] ?? null)

/** The output's video line: what encodes it, at which quality and depth. */
const video = computed(() => {
  const settings = editor.job?.video
  if (settings === undefined || videoStream.value === null) return null
  if (settings.passthrough) return { passthrough: true, encoder: null, quality: null, depth: null }
  const encoder = system.definitions?.video_encoders?.[settings.encoder]
  const control = settings.rate_control
  let quality: string | null = null
  if (control?.mode === 'bitrate') {
    quality = t('summary.units.kbps', { value: n(control.kbps) })
  } else if (control !== undefined) {
    const value = n(control.value, { maximumFractionDigits: 3 })
    const scale = encoder?.rate_control?.quality?.label
    quality = scale ? t('video.quality.valueText', { scale, value }) : value
  }
  return {
    passthrough: false,
    encoder: encoder?.label ?? settings.encoder,
    quality,
    depth: t('summary.video.bits', { bits: settings.bit_depth }),
  }
})

/** Source tracks the output keeps, of all the source's video, audio and subtitle tracks. */
const kept = computed(() => {
  const current = source.value
  const job = editor.job
  if (current === null || job === null) return null
  const total =
    (current.video?.length ?? 0) + (current.audio?.length ?? 0) + (current.subtitles?.length ?? 0)
  const used = new Set<number>()
  if (video.value !== null && videoStream.value !== null) used.add(videoStream.value.index)
  for (const track of job.audio ?? []) {
    if (typeof track.source_stream === 'number') used.add(track.source_stream)
  }
  for (const track of job.subtitles ?? []) {
    if (typeof track.source === 'number') used.add(track.source)
  }
  return total === 0 ? null : t('summary.tracks.kept', { kept: used.size, total })
})

function pale(roles: readonly TrackRoleInfo[], flags: readonly Flag[]): boolean {
  return flags.includes('commentary') || roles.some((role) => role.role === 'commentary')
}

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
</script>

<template>
  <Card class="summary-card summary-card--wide summary-tracks" data-card="tracks">
    <template #header>
      <div class="summary-tracks__header">
        <h3>{{ t('summary.tracks.title') }}</h3>
        <span v-if="kept" class="summary-tracks__kept" data-field="kept">{{ kept }}</span>
      </div>
    </template>
    <div class="summary-tracks__grid">
      <section v-if="video" class="summary-tracks__group" data-group="video">
        <h4 class="summary-tracks__label">{{ t('summary.tracks.video') }}</h4>
        <ul class="summary-tracks__list">
          <li class="summary-tracks__row">
            <button
              type="button"
              class="summary-track"
              data-path="video.encoder"
              @click="ui.reveal('video.encoder')"
            >
              <span class="summary-track__index rf-mono">1</span>
              <span class="summary-track__language">
                <span class="summary-track__mark" aria-hidden="true" />{{
                  t('summary.tracks.video')
                }}
              </span>
              <span class="summary-track__codec">
                <template v-if="video.passthrough">
                  <CodecLabel v-if="videoStream" :stream="videoStream" />
                  <span>{{ t('summary.tracks.passthru') }}</span>
                </template>
                <span v-else>{{ video.encoder }}</span>
              </span>
              <span class="summary-track__value rf-mono">{{ video.quality }}</span>
              <span class="summary-track__roles">{{ video.depth }}</span>
            </button>
          </li>
        </ul>
      </section>
      <section class="summary-tracks__group" data-group="audio">
        <h4 class="summary-tracks__label">{{ t('summary.tracks.audio', audio.length) }}</h4>
        <p v-if="audio.length === 0" class="summary-card__note summary-tracks__empty">
          {{ t('summary.tracks.noAudio') }}
        </p>
        <ul v-else class="summary-tracks__list">
          <li v-for="(chip, index) in audio" :key="chip.path" class="summary-tracks__row">
            <button
              type="button"
              class="summary-track"
              :class="chip.severity && `summary-track--${chip.severity}`"
              :data-path="chip.path"
              @click="ui.reveal(chip.path)"
            >
              <span class="summary-track__index rf-mono">{{ index + 1 }}</span>
              <span class="summary-track__language">
                <LanguageChip :tag="chip.language" :pale="pale(chip.roles, chip.flags)" />
              </span>
              <span class="summary-track__codec">
                <span v-if="chip.from" class="summary-track__from" data-role="from">
                  {{ chip.from }}
                  <ArrowRight class="summary-track__arrow" :size="14" aria-hidden="true" />
                  <span class="rf-sr-only">{{ t('summary.tracks.writtenAs') }}</span>
                </span>
                <template v-if="chip.passthru">
                  <CodecLabel v-if="chip.stream" :stream="chip.stream" />
                  <span v-if="chip.layout">{{ chip.layout }}</span>
                </template>
                <template v-else>
                  <span>{{ chip.encoder }}</span>
                  <span v-if="chip.layout">{{ chip.layout }}</span>
                </template>
                <span
                  v-if="chip.name && chip.sourceName"
                  class="summary-track__from"
                  data-role="renamed-from"
                >
                  {{ chip.sourceName }}
                  <ArrowRight class="summary-track__arrow" :size="14" aria-hidden="true" />
                  <span class="rf-sr-only">{{ t('summary.tracks.renamedTo') }}</span>
                </span>
                <span v-if="chip.name" class="summary-track__name" data-role="name">
                  {{ chip.name }}
                </span>
              </span>
              <span class="summary-track__value rf-mono">
                <template v-if="chip.passthru">{{ t('summary.tracks.passthru') }}</template>
                <template v-else-if="chip.bitrate !== null">
                  {{ t('summary.units.kbps', { value: n(chip.bitrate) }) }}
                </template>
              </span>
              <span class="summary-track__roles">
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
              </span>
            </button>
          </li>
        </ul>
      </section>
      <section class="summary-tracks__group" data-group="subtitles">
        <h4 class="summary-tracks__label">
          {{ t('summary.tracks.subtitles', subtitles.length) }}
        </h4>
        <p v-if="subtitles.length === 0" class="summary-card__note summary-tracks__empty">
          {{ t('summary.tracks.noSubtitles') }}
        </p>
        <ul v-else class="summary-tracks__list">
          <li v-for="(chip, index) in subtitles" :key="chip.path" class="summary-tracks__row">
            <button
              type="button"
              class="summary-track"
              :class="chip.severity && `summary-track--${chip.severity}`"
              :data-path="chip.path"
              @click="ui.reveal(chip.path)"
            >
              <span class="summary-track__index rf-mono">{{ index + 1 }}</span>
              <span class="summary-track__language">
                <LanguageChip :tag="chip.language" :pale="pale(chip.roles, chip.flags)" />
              </span>
              <span class="summary-track__codec">
                <CodecLabel v-if="chip.stream" :stream="chip.stream" />
                <span v-else-if="chip.external" class="summary-track__external">
                  {{ chip.external }}
                </span>
                <template v-if="chip.convertTo && chip.action !== 'burn'">
                  <ArrowRight class="summary-track__arrow" :size="14" aria-hidden="true" />
                  <span class="rf-sr-only">{{ t('summary.tracks.writtenAs') }}</span>
                  <span>{{ chip.convertTo }}</span>
                </template>
                <span v-else-if="chip.action === 'burn'">{{ t('summary.tracks.burn') }}</span>
                <span
                  v-if="chip.name && chip.sourceName"
                  class="summary-track__from"
                  data-role="renamed-from"
                >
                  {{ chip.sourceName }}
                  <ArrowRight class="summary-track__arrow" :size="14" aria-hidden="true" />
                  <span class="rf-sr-only">{{ t('summary.tracks.renamedTo') }}</span>
                </span>
                <span v-if="chip.name" class="summary-track__name" data-role="name">
                  {{ chip.name }}
                </span>
              </span>
              <span class="summary-track__value rf-mono">
                <template v-if="chip.events !== null">
                  {{ t('summary.tracks.events', { n: n(chip.events) }, chip.events) }}
                </template>
              </span>
              <span class="summary-track__roles">
                <RoleBadge
                  v-for="role in chip.roles"
                  :key="role.role"
                  :role="role"
                  kind="subtitle"
                />
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
              </span>
            </button>
          </li>
        </ul>
      </section>
    </div>
  </Card>
</template>

<style scoped>
/* The receipt's lead card: its heading is a step above the other cards'. */
.summary-tracks__header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--rf-space-1) var(--rf-space-3);
}

.summary-tracks__header h3 {
  margin: 0;
  font-size: var(--rf-text-title);
  font-weight: var(--rf-font-weight-bold);
  line-height: var(--rf-line-height-tight);
}

.summary-tracks__kept {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

/* One grid for every group, so that the columns line up from Video to Subtitles. */
.summary-tracks__grid {
  display: grid;
  grid-template-columns:
    [index] 1.5rem [language] minmax(6rem, max-content) [codec] minmax(0, 1fr)
    [value] minmax(4rem, max-content) [roles] minmax(0, max-content);
  column-gap: var(--rf-space-3);
}

.summary-tracks__group,
.summary-tracks__list,
.summary-tracks__row,
.summary-track {
  display: grid;
  grid-column: 1 / -1;
  grid-template-columns: subgrid;
  align-items: center;
}

.summary-tracks__label {
  grid-column: 1 / -1;
  margin: var(--rf-space-4) 0 var(--rf-space-1);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-text-label);
  font-weight: var(--rf-font-weight-medium);
  letter-spacing: var(--rf-tracking-label);
  text-transform: uppercase;
}

.summary-tracks__group:first-child .summary-tracks__label {
  margin-top: var(--rf-space-1);
}

.summary-tracks__empty {
  grid-column: 1 / -1;
  padding: var(--rf-space-2) 0;
  border-top: 1px solid var(--rf-color-border);
}

.summary-tracks__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.summary-tracks__row {
  border-top: 1px solid var(--rf-color-border);
}

.summary-track {
  min-height: 2rem;
  margin: 0 calc(-1 * var(--rf-space-2));
  padding: var(--rf-space-1) var(--rf-space-2);
  border: 0;
  border-radius: var(--rf-radius-sm);
  background: transparent;
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
  outline-offset: -2px;
}

.summary-track--error {
  background: color-mix(in srgb, var(--p-status-error-color) 9%, transparent);
}

.summary-track--warning {
  background: color-mix(in srgb, var(--p-status-warn-color) 9%, transparent);
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
  color: var(--rf-color-text-muted);
}

.summary-track__language {
  display: inline-flex;
  gap: var(--rf-space-2);
  align-items: center;
  min-width: 0;
  white-space: nowrap;
}

/* The video's mark, in ink: the picture has no language. */
.summary-track__mark {
  flex: none;
  width: 0.25rem;
  height: 1rem;
  border-radius: 1px;
  background: var(--rf-color-text);
}

.summary-track__codec {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--rf-space-1);
  align-items: center;
  min-width: 0;
}

.summary-track__codec > .summary-track__name {
  margin-inline-start: var(--rf-space-1);
}

.summary-track__codec :deep(.rf-codec-label) {
  font-weight: var(--rf-font-weight-normal);
}

.summary-track__name,
.summary-track__external {
  min-width: 0;
  color: var(--rf-color-text-muted);
  overflow-wrap: anywhere;
}

.summary-track__from {
  display: inline-flex;
  gap: var(--rf-space-1);
  align-items: center;
  color: var(--rf-color-text-muted);
  white-space: nowrap;
}

.summary-track__arrow {
  flex: none;
  color: var(--rf-color-text-muted);
}

.summary-track__arrow:dir(rtl) {
  transform: scaleX(-1);
}

.summary-track__value {
  white-space: nowrap;
}

.summary-track__roles {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-1) var(--rf-space-2);
  align-items: center;
  justify-content: flex-end;
  color: var(--rf-color-text-muted);
}

.summary-track__flag {
  font-size: var(--rf-font-size-xs);
  white-space: nowrap;
}

/* A narrow card: each row wraps its cells instead of keeping the columns. */
@container (width < 34rem) {
  .summary-tracks__grid,
  .summary-tracks__group,
  .summary-tracks__list,
  .summary-tracks__row {
    display: block;
  }

  .summary-track {
    display: flex;
    flex-wrap: wrap;
    gap: var(--rf-space-1) var(--rf-space-3);
    width: calc(100% + 2 * var(--rf-space-2));
  }

  .summary-track__roles {
    justify-content: flex-start;
  }
}
</style>
