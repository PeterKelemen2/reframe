<script setup lang="ts">
import { Check, ChevronUp, Copy, SquareTerminal } from '@lucide/vue'
import { useClipboard, useLocalStorage, useResizeObserver } from '@vueuse/core'
import Button from 'primevue/button'
import { computed, onBeforeUnmount, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import IssueList from '@/components/base/IssueList.vue'

import { stepLines, tokenize } from './commandLine'
import { useCommandPlan } from './useCommandPlan'

/** The job's full FFmpeg command (`jobs/plan`), kept current while the drawer is open. */
const { t } = useI18n()
const bodyId = useId()

const open = useLocalStorage('reframe.video.commandOpen', false)
const { plan, problem, pending } = useCommandPlan(open)
const { copy, copied, isSupported } = useClipboard({ legacy: true, copiedDuring: 2000 })

const lines = computed(() => (plan.value === null ? [] : stepLines(tokenize(plan.value.display))))

async function copyCommand(): Promise<void> {
  if (plan.value !== null) await copy(plan.value.display)
}

// The tab's scroller keeps a focused control clear of the drawer by its height.
const DRAWER_HEIGHT = '--video-command-drawer-height'
const root = useTemplateRef<HTMLElement>('root')
useResizeObserver(root, ([entry]) => {
  const height = entry?.borderBoxSize?.[0]?.blockSize ?? entry?.contentRect.height ?? 0
  document.documentElement.style.setProperty(DRAWER_HEIGHT, `${Math.ceil(height)}px`)
})
onBeforeUnmount(() => document.documentElement.style.removeProperty(DRAWER_HEIGHT))
</script>

<template>
  <aside ref="root" class="command-preview" :class="{ 'command-preview--open': open }">
    <div class="command-preview__bar">
      <button
        type="button"
        class="command-preview__toggle"
        :aria-expanded="open"
        :aria-controls="bodyId"
        @click="open = !open"
      >
        <SquareTerminal :size="18" aria-hidden="true" />
        <span>{{ t('video.command.title') }}</span>
        <ChevronUp class="command-preview__chevron" :size="18" aria-hidden="true" />
      </button>
      <span v-if="open && pending" class="command-preview__pending">{{
        t('video.command.updating')
      }}</span>
      <Button
        v-if="open && plan !== null && isSupported"
        class="command-preview__copy"
        size="small"
        severity="secondary"
        text
        :label="copied ? t('video.command.copied') : t('video.command.copy')"
        @click="copyCommand"
      >
        <template #icon>
          <Check v-if="copied" :size="16" aria-hidden="true" />
          <Copy v-else :size="16" aria-hidden="true" />
        </template>
      </Button>
      <span class="rf-sr-only" aria-live="polite">{{
        copied ? t('video.command.copied') : ''
      }}</span>
    </div>
    <div v-if="open" :id="bodyId" class="command-preview__body">
      <pre
        v-if="plan !== null"
        class="command-preview__code"
        :class="{ 'command-preview__code--stale': pending }"
        tabindex="0"
        :aria-label="t('video.command.code')"
      ><code><span
        v-for="(line, row) in lines"
        :key="row"
        class="command-preview__line"
      ><span
        v-for="(token, column) in line"
        :key="column"
        :class="`cmd-${token.kind}`"
      >{{ token.text }}</span></span></code></pre>
      <div v-else-if="problem?.kind === 'invalid'" class="command-preview__problem">
        <p>{{ t('video.command.invalid') }}</p>
        <IssueList :issues="problem.issues" />
      </div>
      <p v-else-if="problem?.kind === 'failed'" class="command-preview__problem">
        {{ t('video.command.failed', { reason: problem.message }) }}
      </p>
      <p v-else class="command-preview__problem">{{ t('video.command.loading') }}</p>
    </div>
  </aside>
</template>

<style scoped>
.command-preview {
  position: sticky;
  bottom: 0;
  z-index: 1;
  border: 1px solid var(--rf-color-border);
  border-radius: var(--rf-radius-md) var(--rf-radius-md) 0 0;
  background: var(--rf-color-surface);
  box-shadow: 0 -2px 8px rgb(0 0 0 / 8%);
}

/*
 * A field's bar is drawn in the panel's side padding, which the drawer does not cover. The
 * middle of the gradient stays clear: it is painted over the drawer's own border.
 */
.command-preview::before {
  content: '';
  position: absolute;
  inset-block: -1px;
  inset-inline: calc(-1 * (var(--rf-space-4) + 1px));
  z-index: -1;
  background: linear-gradient(
    to right,
    var(--rf-color-surface) var(--rf-space-4),
    transparent var(--rf-space-4) calc(100% - var(--rf-space-4)),
    var(--rf-color-surface) calc(100% - var(--rf-space-4))
  );
}

.command-preview__bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--rf-space-3);
  min-height: 2.5rem;
  padding-inline: var(--rf-space-3);
}

.command-preview__toggle {
  display: inline-flex;
  flex: 1;
  align-items: center;
  gap: var(--rf-space-2);
  padding: var(--rf-space-2) 0;
  border: 0;
  background: none;
  color: var(--rf-color-text);
  font: inherit;
  font-weight: var(--rf-font-weight-medium);
  text-align: start;
  cursor: pointer;
}

.command-preview__chevron {
  transition: transform var(--rf-duration) ease;
}

.command-preview--open .command-preview__chevron {
  transform: rotate(180deg);
}

.command-preview__pending {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

/* The tab's height (a size container), or the viewport's without one: the options stay in view. */
.command-preview--open {
  display: flex;
  flex-direction: column;
  max-height: 40cqh;
}

.command-preview__body {
  min-height: 0;
  overflow: auto;
  border-top: 1px solid var(--rf-color-border);
  padding: var(--rf-space-3);
}

.command-preview__code {
  margin: 0;
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.command-preview__line {
  display: block;
}

.command-preview__line + .command-preview__line {
  margin-top: var(--rf-space-2);
}

.command-preview__problem {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  color: var(--rf-color-text);
}

.command-preview__problem p {
  margin: 0;
}

.cmd-program {
  font-weight: var(--rf-font-weight-bold);
}

.cmd-option {
  color: var(--rf-color-primary);
  white-space: nowrap;
}

.cmd-path {
  color: var(--p-status-ok-color);
}

.cmd-filter {
  color: var(--p-status-warn-color);
}

.cmd-operator {
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-bold);
}
</style>
