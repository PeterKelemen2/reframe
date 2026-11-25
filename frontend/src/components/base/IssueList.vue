<script setup lang="ts">
import Button from 'primevue/button'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import type { Fix, ValidationIssue } from '@/api/types'
import { useEditorStore } from '@/stores/editor'
import { useSystemStore } from '@/stores/system'
import { useUiStore } from '@/stores/ui'

import { bySeverity, SEVERITY_ICON, useSeverityLabel } from './severity'

/**
 * Issues, most severe first, each with its fix buttons (`editor.applyFix`) and a link to its
 * field (`ui.reveal(issue.path)`). An unavailable video encoder that another FFmpeg build can
 * make available adds *Use another FFmpeg…*; frames that disagree on the crop add *Check crop on
 * all frames*. Used by the Summary tab and the status bar.
 */
const props = defineProps<{
  issues: ValidationIssue[]
  /** Tighter rows, for the status bar's list. */
  compact?: boolean
}>()

const { t } = useI18n()
const severityLabel = useSeverityLabel()
const editor = useEditorStore()
const system = useSystemStore()
const ui = useUiStore()
const router = useRouter()

const sorted = computed(() => bySeverity(props.issues))
/** The fix being applied: every fix button waits for it, so that two patches never race. */
const applying = ref<Fix | null>(null)

function buildMismatch(issue: ValidationIssue): boolean {
  if (issue.code !== 'encoder.unavailable' || issue.path !== 'video.encoder') return false
  const encoder = editor.job?.video?.encoder
  return encoder !== undefined && system.encoderStatus(encoder)?.build_mismatch === true
}

async function otherFfmpeg(): Promise<void> {
  await router.push({ name: 'settings', hash: '#tools' })
}

async function applyFix(fix: Fix): Promise<void> {
  if (applying.value !== null) return
  applying.value = fix
  try {
    await editor.applyFix(fix)
  } finally {
    applying.value = null
  }
}
</script>

<template>
  <p v-if="sorted.length === 0" class="rf-issue-list__empty">{{ t('base.issues.none') }}</p>
  <ul v-else class="rf-issue-list" :class="{ 'rf-issue-list--compact': compact }">
    <li
      v-for="(issue, index) in sorted"
      :key="`${issue.code}:${issue.path}:${index}`"
      class="rf-issue"
      :class="`rf-issue--${issue.severity}`"
      :data-severity="issue.severity"
    >
      <component
        :is="SEVERITY_ICON[issue.severity]"
        class="rf-issue__icon"
        :size="16"
        aria-hidden="true"
      />
      <span class="rf-sr-only">{{ severityLabel(issue.severity) }}: </span>
      <span class="rf-issue__message">{{ issue.message }}</span>
      <span class="rf-issue__actions">
        <Button
          v-if="issue.path"
          class="rf-issue__reveal"
          link
          size="small"
          :label="t('base.issues.show')"
          :aria-label="t('base.issues.showField', { message: issue.message })"
          @click="ui.reveal(issue.path)"
        />
        <Button
          v-for="fix in issue.fixes ?? []"
          :key="fix.label"
          class="rf-issue__fix"
          size="small"
          severity="secondary"
          outlined
          :label="fix.label"
          :loading="applying === fix"
          :disabled="applying !== null"
          @click="applyFix(fix)"
        />
        <Button
          v-if="issue.code === 'dimensions.crop_frames_disagree'"
          class="rf-issue__check-crop"
          size="small"
          severity="secondary"
          outlined
          :label="t('crop.magnifier.check')"
          @click="ui.checkCrop()"
        />
        <Button
          v-if="buildMismatch(issue)"
          class="rf-issue__other-ffmpeg"
          size="small"
          severity="secondary"
          outlined
          :label="t('base.issues.otherFfmpeg')"
          @click="otherFfmpeg"
        />
      </span>
    </li>
  </ul>
</template>

<style scoped>
.rf-issue-list {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.rf-issue {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: var(--rf-space-1) var(--rf-space-2);
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--rf-issue-border);
  border-radius: var(--rf-radius-md);
  background: var(--rf-issue-background);
  color: var(--rf-color-text);
}

.rf-issue--error {
  --rf-issue-accent: var(--p-status-error-color);
  --rf-issue-border: var(--p-status-error-border-color);
  --rf-issue-background: var(--p-status-error-background);
}

.rf-issue--warning {
  --rf-issue-accent: var(--p-status-warn-color);
  --rf-issue-border: var(--p-status-warn-border-color);
  --rf-issue-background: var(--p-status-warn-background);
}

.rf-issue--info {
  --rf-issue-accent: var(--p-status-info-color);
  --rf-issue-border: var(--p-status-info-border-color);
  --rf-issue-background: var(--p-status-info-background);
}

.rf-issue__icon {
  margin-top: 0.2em;
  color: var(--rf-issue-accent);
}

.rf-issue__message {
  grid-column: 2;
  overflow-wrap: anywhere;
}

.rf-issue__actions {
  display: flex;
  flex-wrap: wrap;
  grid-column: 2;
  align-items: center;
  gap: var(--rf-space-2);
}

.rf-issue__actions:empty {
  display: none;
}

.rf-issue-list--compact {
  gap: var(--rf-space-1);
}

.rf-issue-list--compact .rf-issue {
  padding: var(--rf-space-1) var(--rf-space-2);
  font-size: var(--rf-font-size-sm);
}

.rf-issue-list__empty {
  margin: 0;
  color: var(--rf-color-text-muted);
}
</style>
