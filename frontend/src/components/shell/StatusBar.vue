<script lang="ts">
/** The CSS variable with the status bar's height while it is shown (toasts keep clear of it). */
export const STATUS_BAR_HEIGHT = '--shell-status-bar-height'
</script>

<script setup lang="ts">
import { ListVideo, LoaderCircle, Play, Plus } from '@lucide/vue'
import { useResizeObserver } from '@vueuse/core'
import Button from 'primevue/button'
import vTooltip from 'primevue/tooltip'
import { computed, nextTick, onBeforeUnmount, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'

import ApplyToGroupDialog from '@/components/batch/ApplyToGroupDialog.vue'
import { useQueueActions } from '@/composables/useQueueActions'
import { useEditorStore } from '@/stores/editor'
import { useQueueStore } from '@/stores/queue'
import { useSourcesStore } from '@/stores/sources'

import ConnectionStatus from './ConnectionStatus.vue'
import { focusLost } from './focus'
import FocusSafeButton from './FocusSafeButton'
import { identityParts, jobIdentity } from './identity'
import ValidationSummary from './ValidationSummary.vue'

const { t } = useI18n()
const editor = useEditorStore()
const queue = useQueueStore()
const sources = useSourcesStore()
const actions = useQueueActions()
const id = useId()
const { canAdd, canAddOnly, canAddAll, canStart, busy, activeGroup, changes } = actions

/** The button whose add is under way shows the wait; a shortcut's add is the primary one's. */
const adding = ref<'only' | 'all' | null>(null)

async function run(which: 'only' | 'all', action: () => Promise<void>): Promise<void> {
  adding.value = which
  try {
    await action()
  } finally {
    adding.value = null
  }
}

const addLabel = computed(() => {
  const group = activeGroup.value
  if (group === null) return t('shell.queue.add')
  const key = group.episodes ? 'shell.queue.addEpisodes' : 'shell.queue.addFiles'
  return t(key, { n: group.count }, group.count)
})

const only = computed(() => {
  const label = activeGroup.value?.label ?? null
  return label === null
    ? { text: t('shell.queue.onlyThis'), name: t('shell.queue.onlyThisLabel') }
    : { text: t('shell.queue.only', { label }), name: t('shell.queue.onlyLabel', { label }) }
})

const shortcut = computed(() => t('shell.queue.shortcut', { key: t('shell.keys.addToQueue') }))

const root = useTemplateRef<HTMLElement>('root')

// The question belongs to the file it was asked about.
watch(
  () => editor.session,
  () => actions.dismissChanges(),
)

function focusAdd(): void {
  void nextTick(() => {
    if (focusLost()) root.value?.querySelector<HTMLElement>('.status-bar__add')?.focus()
  })
}

watch(
  () => changes.value !== null,
  async (asked) => {
    if (!asked) return
    await nextTick()
    root.value?.querySelector<HTMLElement>('[data-action="changes-apply"]')?.focus()
  },
)

const apply = ref<{ groupId: string; name: string } | null>(null)
const applyOpen = ref(false)

function applyFirst(): void {
  const asked = changes.value
  actions.dismissChanges()
  if (asked === null) return
  const name = sources.grouping?.groups?.find((group) => group.id === asked.groupId)?.name ?? ''
  apply.value = { groupId: asked.groupId, name }
  applyOpen.value = true
}

function cancelChanges(): void {
  actions.dismissChanges()
  focusAdd()
}

function queueWithoutChanges(): void {
  void actions.addGroup()
  focusAdd()
}

const outputPath = computed(() => editor.job?.output?.path || null)

/** `The Sopranos · S03E02 · MKV`: the parsed name of the shown file, once its draft is in. */
const identity = computed(() => {
  const job = editor.job
  if (job === null) return null
  const path = job.source.path
  const draft = editor.draft?.job.source.path === path ? editor.draft : null
  return jobIdentity(identityParts(draft?.naming?.fields, path, job.output?.container))
})

useResizeObserver(root, ([entry]) => {
  const height = entry?.borderBoxSize?.[0]?.blockSize ?? entry?.contentRect.height ?? 0
  document.documentElement.style.setProperty(STATUS_BAR_HEIGHT, `${Math.ceil(height)}px`)
})
onBeforeUnmount(() => document.documentElement.style.removeProperty(STATUS_BAR_HEIGHT))

const queueSummary = computed(() => {
  const { running, paused, waiting } = queue.counts
  const parts: string[] = []
  if (running > 0) parts.push(t('shell.queue.running', { n: running }))
  if (paused > 0) parts.push(t('shell.queue.paused', { n: paused }))
  if (waiting > 0) parts.push(t('shell.queue.waiting', { n: waiting }))
  return parts.length === 0
    ? t('shell.queue.idle')
    : t('shell.queue.summary', { parts: parts.join(' · ') })
})
</script>

<template>
  <section ref="root" class="status-bar" :aria-label="t('shell.status.label')">
    <div
      v-if="changes"
      class="status-bar__changes"
      role="alertdialog"
      :aria-labelledby="`${id}-changes`"
      data-state="changes"
      @keydown.esc.stop.prevent="cancelChanges"
    >
      <p :id="`${id}-changes`" class="status-bar__changes-text">
        {{ t('shell.queue.changes.text', { label: changes.label }) }}
      </p>
      <div class="status-bar__changes-actions">
        <Button
          size="small"
          :label="t('shell.queue.changes.apply')"
          data-action="changes-apply"
          @click="applyFirst"
        />
        <Button
          size="small"
          severity="secondary"
          outlined
          :label="t('shell.queue.changes.queue')"
          data-action="changes-queue"
          @click="queueWithoutChanges"
        />
        <Button
          size="small"
          severity="secondary"
          text
          :label="t('shell.queue.changes.cancel')"
          data-action="changes-cancel"
          @click="cancelChanges"
        />
      </div>
    </div>
    <span v-if="identity" class="status-bar__identity" data-field="identity">{{ identity }}</span>
    <div class="status-bar__output" data-field="output">
      <span class="status-bar__caption">{{ t('shell.status.output') }}</span>
      <span
        v-if="outputPath"
        v-tooltip.top="outputPath"
        class="status-bar__path"
        data-field="output-path"
      >
        <span dir="ltr">{{ outputPath }}</span>
      </span>
      <span v-else class="status-bar__path status-bar__path--none">
        {{ t('shell.status.noOutput') }}
      </span>
    </div>
    <ValidationSummary v-if="editor.job !== null" />
    <ConnectionStatus />
    <RouterLink to="/queue" class="status-bar__queue" data-field="queue">
      <ListVideo :size="16" aria-hidden="true" />
      {{ queueSummary }}
    </RouterLink>
    <div class="status-bar__actions">
      <FocusSafeButton
        class="status-bar__add-all"
        size="small"
        severity="secondary"
        text
        :label="t('shell.queue.addAll')"
        :disabled="!canAddAll"
        :aria-busy="(busy && adding === 'all') || undefined"
        @click="run('all', actions.addAll)"
      >
        <template v-if="busy && adding === 'all'" #icon>
          <LoaderCircle class="status-bar__spin" :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        v-if="activeGroup"
        class="status-bar__only"
        size="small"
        severity="secondary"
        outlined
        :label="only.text"
        :aria-label="only.name"
        :disabled="!canAddOnly"
        :aria-busy="(busy && adding === 'only') || undefined"
        @click="run('only', actions.addOnly)"
      >
        <template v-if="busy && adding === 'only'" #icon>
          <LoaderCircle class="status-bar__spin" :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        v-tooltip.top="shortcut"
        class="status-bar__add"
        size="small"
        :label="addLabel"
        :disabled="!canAdd"
        :aria-busy="(busy && adding === null) || undefined"
        aria-keyshortcuts="Control+Enter"
        @click="actions.addCurrent()"
      >
        <template #icon>
          <LoaderCircle
            v-if="busy && adding === null"
            class="status-bar__spin"
            :size="16"
            aria-hidden="true"
          />
          <Plus v-else :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
      <FocusSafeButton
        class="status-bar__start"
        size="small"
        severity="secondary"
        outlined
        :label="t('shell.queue.start')"
        :disabled="!canStart"
        @click="actions.start()"
      >
        <template #icon>
          <Play :size="16" aria-hidden="true" />
        </template>
      </FocusSafeButton>
    </div>
    <ApplyToGroupDialog
      v-if="apply"
      v-model:visible="applyOpen"
      :group-id="apply.groupId"
      :group-name="apply.name"
      @closed="focusAdd"
    />
  </section>
</template>

<style scoped>
.status-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  min-height: 3.5rem;
  padding: var(--rf-space-2) var(--rf-space-4);
  border-top: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
  font-size: var(--rf-font-size-sm);
}

.status-bar__identity {
  overflow: hidden;
  flex: 0 1 auto;
  min-width: 0;
  max-width: 22rem;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-bar__output {
  display: flex;
  flex: 1 1 14rem;
  align-items: baseline;
  gap: var(--rf-space-2);
  min-width: 0;
}

.status-bar__caption {
  flex: none;
  color: var(--rf-color-text-muted);
}

.status-bar__path {
  overflow: hidden;
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
  /* The file name at the end matters most: the ellipsis cuts the start of the path. */
  direction: rtl;
  text-align: left;
}

.status-bar__path--none {
  font-family: inherit;
  font-size: inherit;
  color: var(--rf-color-text-muted);
  direction: ltr;
}

.status-bar__queue {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
  border-radius: var(--rf-radius-sm);
  color: var(--rf-color-text-muted);
  text-decoration: none;
}

.status-bar__queue:hover,
.status-bar__queue:focus-visible {
  color: var(--rf-color-text);
  text-decoration: underline;
}

.status-bar__spin {
  animation: status-bar-spin 1s linear infinite;
}

@keyframes status-bar-spin {
  to {
    transform: rotate(360deg);
  }
}

.status-bar__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  margin-left: auto;
}

.status-bar__changes {
  display: flex;
  flex: 1 1 100%;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  padding: var(--rf-space-2) var(--rf-space-3);
  border: 1px solid var(--p-status-warn-border-color);
  border-radius: var(--rf-radius-md);
  background: var(--p-status-warn-background);
}

.status-bar__changes-text {
  flex: 1 1 24rem;
  margin: 0;
}

.status-bar__changes-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}
</style>
