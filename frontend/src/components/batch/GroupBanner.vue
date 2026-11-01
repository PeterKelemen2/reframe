<script setup lang="ts">
// Above the tabs: the edited group (its file count, the shown file, the scope, its actions), or
// a slim line while a file of a group is open as one job. Nothing otherwise.
import { LoaderCircle } from '@lucide/vue'
import Button from 'primevue/button'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed, nextTick, ref, useId, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { apiQuiet, ApiError, unwrap } from '@/api/client'
import PresetNameDialog, {
  type PresetDetailsInput,
} from '@/components/presets/PresetNameDialog.vue'
import { focusFirstIn, focusLost } from '@/components/shell/focus'
import { type PanelItem, panelItems } from '@/components/sources/panel'
import { useQueueGroup } from '@/composables/useQueueGroup'
import { type GroupScope, useEditorStore } from '@/stores/editor'
import { usePresetsStore } from '@/stores/presets'
import { useSourcesStore } from '@/stores/sources'
import { useToastStore } from '@/stores/toasts'
import { useUiStore } from '@/stores/ui'

import ApplyToGroupDialog from './ApplyToGroupDialog.vue'

type GroupItem = Extract<PanelItem, { kind: 'group' }>

const { t } = useI18n()
const editor = useEditorStore()
const sources = useSourcesStore()
const presets = usePresetsStore()
const toasts = useToastStore()
const ui = useUiStore()
const { busy: queueing, queueGroup } = useQueueGroup()
const id = useId()

const root = useTemplateRef<HTMLElement>('root')
const applyOpen = ref(false)
const saveOpen = ref(false)

const groups = computed(() =>
  panelItems(sources.entries, sources.grouping).filter(
    (item): item is GroupItem => item.kind === 'group',
  ),
)

const groupTarget = computed(() => (editor.target?.kind === 'group' ? editor.target : null))

/** The edited group, labelled as the sources panel labels it. */
const edited = computed<GroupItem | null>(() => {
  const target = groupTarget.value
  if (target === null) return null
  return groups.value.find((item) => item.group.id === target.groupId) ?? null
})

/** The group of the file open as one job. */
const memberOf = computed<GroupItem | null>(() => {
  const target = editor.target
  if (target?.kind !== 'job') return null
  return (
    groups.value.find((item) => item.rows.some((row) => row.entry.id === target.sourceId)) ?? null
  )
})

const shownLabel = computed(
  () => edited.value?.rows.find((row) => row.entry.id === groupTarget.value?.sourceId)?.label ?? '',
)

const fileOptions = computed(() =>
  (edited.value?.rows ?? []).map((row) => ({ label: row.label, value: row.entry.id })),
)

const scopeOptions = computed(() => [
  { label: t('group.banner.scopeGroup'), value: 'group' },
  { label: t('group.banner.scopeFile', { label: shownLabel.value }), value: 'file' },
])

/** An `ApiError` was shown as a toast by the API client; anything else is a bug. */
async function quietly(action: () => Promise<unknown>): Promise<void> {
  try {
    await action()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  }
}

function showFile(sourceId: string): Promise<void> {
  return quietly(() => editor.showFile(sourceId))
}

function setScope(scope: GroupScope): Promise<void> {
  return quietly(() => editor.setScope(scope))
}

function editGroup(groupId: string): Promise<void> {
  return quietly(() => editor.editGroup(groupId))
}

function closeGroup(): Promise<void> {
  const target = groupTarget.value
  if (target === null) return Promise.resolve()
  return quietly(() => sources.select(target.sourceId))
}

const saveInitial: PresetDetailsInput = { name: '', category: 'Custom', description: '' }

/** The template alone becomes the preset: an override belongs to its file. */
async function saveAsPreset(details: PresetDetailsInput): Promise<void> {
  const target = groupTarget.value
  if (target === null) return
  const saved = unwrap(
    await apiQuiet.POST('/api/batch/save-preset', {
      body: { template: target.template, ...details },
    }),
  )
  toasts.push({
    severity: 'success',
    summary: t('group.preset.saved', { name: saved.name }),
    life: 5000,
  })
  await quietly(async () => {
    await presets.load()
    const now = editor.target
    if (now?.kind === 'group' && now.groupId === target.groupId) {
      await editor.applyPreset(saved.id)
    }
  })
}

function focusIn(selector: string): void {
  if (focusLost()) root.value?.querySelector<HTMLElement>(selector)?.focus()
}

// The control that was used may leave with its banner (*Close group*, *Edit group*).
const mode = computed(() => (edited.value ? 'group' : memberOf.value ? 'member' : null))
watch(mode, async () => {
  await nextTick()
  if (focusLost()) focusFirstIn(root.value)
})
</script>

<template>
  <div ref="root" class="group-banner-root">
    <div
      v-if="edited && groupTarget"
      class="group-banner"
      role="region"
      :aria-label="t('group.banner.label')"
      data-state="group"
    >
      <p class="group-banner__title" data-field="title">
        {{
          t(
            'group.banner.editing',
            { name: edited.group.name, count: edited.rows.length, label: shownLabel },
            edited.rows.length,
          )
        }}
      </p>
      <div class="group-banner__controls">
        <span :id="`${id}-shown`" class="group-banner__label">{{ t('group.banner.shown') }}</span>
        <Select
          class="group-banner__switcher"
          :model-value="groupTarget.sourceId"
          :options="fileOptions"
          option-label="label"
          option-value="value"
          :ariaLabelledby="`${id}-shown`"
          size="small"
          data-field="shown"
          @update:model-value="showFile"
        />
        <span :id="`${id}-scope`" class="group-banner__label">{{ t('group.banner.scope') }}</span>
        <SelectButton
          :model-value="groupTarget.scope"
          :options="scopeOptions"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          :ariaLabelledby="`${id}-scope`"
          size="small"
          data-field="scope"
          @update:model-value="setScope"
        />
      </div>
      <div class="group-banner__actions">
        <Button
          size="small"
          :label="t('group.actions.check')"
          data-action="check-group"
          @click="ui.openMatrix()"
        />
        <!-- Busy, not disabled: the focus stays here, and a second click is refused. -->
        <Button
          size="small"
          severity="secondary"
          :label="t('group.actions.queue')"
          :aria-busy="queueing || undefined"
          data-action="queue-group"
          @click="queueGroup(groupTarget.groupId)"
        >
          <template v-if="queueing" #icon>
            <LoaderCircle class="group-banner__spin" :size="16" aria-hidden="true" />
          </template>
        </Button>
        <Button
          size="small"
          severity="secondary"
          :label="t('group.actions.saveAsPreset')"
          data-action="save-as-preset"
          @click="saveOpen = true"
        />
        <Button
          size="small"
          severity="secondary"
          text
          :label="t('group.actions.close')"
          data-action="close-group"
          @click="closeGroup"
        />
      </div>
    </div>
    <div v-else-if="memberOf" class="group-banner group-banner--slim" data-state="member">
      <span class="group-banner__title" data-field="title">{{
        t('group.banner.inGroup', { name: memberOf.group.name })
      }}</span>
      <div class="group-banner__actions">
        <Button
          size="small"
          severity="secondary"
          :label="t('group.actions.applyToGroup')"
          data-action="apply-to-group"
          @click="applyOpen = true"
        />
        <Button
          size="small"
          severity="secondary"
          text
          :label="t('group.actions.edit')"
          data-action="edit-group"
          @click="editGroup(memberOf.group.id)"
        />
      </div>
      <ApplyToGroupDialog
        v-model:visible="applyOpen"
        :group-id="memberOf.group.id"
        :group-name="memberOf.group.name"
        @closed="focusIn('[data-action=apply-to-group]')"
      />
    </div>
    <PresetNameDialog
      v-model:visible="saveOpen"
      :title="t('group.preset.title')"
      :submit-label="t('group.preset.save')"
      :initial="saveInitial"
      :save="saveAsPreset"
      @closed="focusIn('[data-action=save-as-preset]')"
    />
  </div>
</template>

<style scoped>
.group-banner__spin {
  animation: group-banner-spin 1s linear infinite;
}

@keyframes group-banner-spin {
  to {
    transform: rotate(360deg);
  }
}

.group-banner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-4);
  padding: var(--rf-space-2) var(--rf-space-4);
  border-bottom: 1px solid var(--rf-color-border);
  border-left: 3px solid var(--rf-color-primary);
  background: color-mix(in srgb, var(--rf-color-primary) 8%, var(--rf-color-surface));
}

.group-banner--slim {
  padding-block: var(--rf-space-1);
  border-left-color: var(--rf-color-border);
  background: var(--rf-color-surface);
}

.group-banner__title {
  margin: 0;
  font-weight: var(--rf-font-weight-medium);
}

.group-banner--slim .group-banner__title {
  color: var(--rf-color-text-muted);
  font-weight: normal;
}

.group-banner__controls,
.group-banner__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.group-banner__actions {
  margin-inline-start: auto;
}

.group-banner__label {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.group-banner__switcher {
  min-width: 7rem;
}
</style>
