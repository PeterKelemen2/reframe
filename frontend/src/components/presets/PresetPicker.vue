<script setup lang="ts">
import { ChevronDown, Ellipsis, Lock, Star } from '@lucide/vue'
import Button from 'primevue/button'
import Listbox from 'primevue/listbox'
import Menu from 'primevue/menu'
import Popover from 'primevue/popover'
import { computed, nextTick, onMounted, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { FieldChange, JobTemplate, JsonPatchOp, Preset } from '@/api/types'
import { focusFirstIn, focusLost } from '@/components/shell/focus'
import { useEditorStore } from '@/stores/editor'
import { usePresetsStore } from '@/stores/presets'
import { hasPointer } from '@/stores/settings'
import { useToastStore } from '@/stores/toasts'

import PresetChanges from './PresetChanges.vue'
import PresetNameDialog, { type PresetDetailsInput } from './PresetNameDialog.vue'

const { t } = useI18n()
const editor = useEditorStore()
const presets = usePresetsStore()
const toasts = useToastStore()
const router = useRouter()

const id = useId()
const labelId = `${id}-label`
const listId = `${id}-list`
const changesId = `${id}-changes`
const root = useTemplateRef<HTMLElement>('root')
const listPopover = useTemplateRef<InstanceType<typeof Popover>>('listPopover')
const changesPopover = useTemplateRef<InstanceType<typeof Popover>>('changesPopover')
const actionsMenu = useTemplateRef<InstanceType<typeof Menu>>('actionsMenu')
const listOpen = ref(false)
const changesOpen = ref(false)
const saveAsOpen = ref(false)
const updating = ref(false)

onMounted(() => void presets.ensureLoaded().catch(() => undefined))

const job = computed(() => editor.job ?? null)
const presetId = computed<string | null>(() => editor.presetId ?? null)
const preset = computed<Preset | null>(() => editor.preset ?? null)
const template = computed<JobTemplate | null>(() => editor.currentTemplate ?? null)
const changes = computed<FieldChange[]>(() => editor.presetChanges ?? [])
const modified = computed(() => job.value !== null && changes.value.length > 0)

interface Option {
  label: string
  value: string
  builtIn: boolean
  isDefault: boolean
}

const groups = computed(() =>
  presets.categories.map((category) => ({
    label: category.name,
    items: category.presets.map<Option>((item) => ({
      label: item.name,
      value: item.id,
      builtIn: item.built_in,
      isDefault: item.id === presets.defaultId,
    })),
  })),
)

const current = computed(() => {
  if (job.value === null) return t('presets.picker.noJob')
  return preset.value?.name ?? job.value.preset_name ?? t('presets.picker.none')
})

/** The job's preset is not on the server any more (deleted elsewhere). */
const missing = computed(
  () =>
    presets.loaded &&
    presetId.value !== null &&
    preset.value === null &&
    presets.byId(presetId.value) === undefined,
)

/** A user preset that the current settings can be saved into. */
const updatable = computed<Preset | null>(() =>
  preset.value !== null && !preset.value.built_in && template.value !== null ? preset.value : null,
)

function focusTrigger(): void {
  root.value?.querySelector<HTMLElement>('.preset-picker__trigger')?.focus()
}

function toggleList(event: Event): void {
  listPopover.value?.toggle(event)
}

async function listShown(): Promise<void> {
  listOpen.value = true
  void presets.load().catch(() => undefined)
  await nextTick()
  document.querySelector<HTMLElement>(`#${CSS.escape(listId)} .p-listbox-filter`)?.focus()
}

function listHidden(): void {
  listOpen.value = false
  // The list goes away with the focus in it: the focus goes back to where the list opened. Not
  // before this key's events end: an Enter that reached the button would open the list again.
  const focused = document.activeElement
  if (focused === document.body || document.getElementById(listId)?.contains(focused)) {
    setTimeout(focusTrigger)
  }
}

async function choose(chosen: string | null): Promise<void> {
  listPopover.value?.hide()
  // The listbox gives `null` for a click on the job's own preset.
  if (chosen === null || job.value === null) return
  try {
    await editor.applyPreset(chosen)
  } catch (error) {
    // The draft's problem is a toast already.
    if (!(error instanceof ApiError)) throw error
  }
}

function toggleChanges(event: Event): void {
  changesPopover.value?.toggle(event)
}

function changesShown(): void {
  changesOpen.value = true
  focusFirstIn(document.getElementById(changesId))
}

/** The job follows the preset that Save as new made: its marker is about to go. */
let savedAs = false

// The dialog gives the focus back to its button in the changes, which closed when it opened.
function saveAsClosed(): void {
  if (!focusLost()) return
  const marker = root.value?.querySelector<HTMLElement>('.preset-picker__modified')
  if (marker && !savedAs) marker.focus()
  else focusTrigger()
}

const saveAsInitial = computed<PresetDetailsInput>(() => ({
  name: '',
  category: preset.value !== null && !preset.value.built_in ? preset.value.category : 'Custom',
  description: '',
}))

/** Saves the current settings as a new preset, and the job then follows that preset. */
async function saveAs(details: PresetDetailsInput): Promise<void> {
  if (template.value === null) return
  // Only the job the settings came from follows the new preset: by the answer, another source
  // or another preset may be open.
  const session = editor.session
  const from = presetId.value
  const created = await presets.create({ template: template.value, ...details })
  toasts.push({
    severity: 'success',
    summary: t('presets.picker.saved', { name: created.name }),
    life: 5000,
  })
  const opened = job.value
  if (opened === null || editor.session !== session || presetId.value !== from) return
  savedAs = true
  const op = (path: string) => (hasPointer(opened, path) ? 'replace' : 'add')
  editor.patch([
    { op: op('/preset_id'), path: '/preset_id', value: created.id },
    { op: op('/preset_name'), path: '/preset_name', value: created.name },
  ] as JsonPatchOp[])
}

async function update(): Promise<void> {
  const target = updatable.value
  const settings = template.value
  if (target === null || settings === null || updating.value) return
  updating.value = true
  try {
    await presets.save({
      ...settings,
      id: target.id,
      name: target.name,
      category: target.category,
      description: target.description,
      built_in: false,
    })
    editor.refreshPresetChanges()
    toasts.push({
      severity: 'success',
      summary: t('presets.picker.updated', { name: target.name }),
      life: 5000,
    })
    // The marker goes with the changes: the focus waits on the preset button.
    if (document.getElementById(changesId)?.contains(document.activeElement)) focusTrigger()
    changesPopover.value?.hide()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    toasts.push({
      severity: 'error',
      summary: t('presets.picker.updateFailed', { name: target.name }),
      detail: error.problem.detail ?? error.problem.title,
      life: 10_000,
    })
  } finally {
    updating.value = false
  }
}

function openSaveAs(): void {
  changesPopover.value?.hide()
  savedAs = false
  saveAsOpen.value = true
}

function openPresets(): void {
  changesPopover.value?.hide()
  void router.push({
    name: 'presets',
    query: presetId.value === null ? {} : { preset: presetId.value },
  })
}

const menuItems = computed(() => [
  { label: t('presets.picker.saveAs'), disabled: template.value === null, command: openSaveAs },
  {
    label: t('presets.picker.update'),
    disabled: updatable.value === null || !modified.value,
    command: () => void update(),
  },
  { separator: true },
  { label: t('presets.picker.open'), command: openPresets },
])

function toggleMenu(event: Event): void {
  actionsMenu.value?.toggle(event)
}
</script>

<template>
  <div ref="root" class="preset-picker">
    <span :id="labelId" class="preset-picker__label">{{ t('presets.picker.label') }}</span>
    <Button
      class="preset-picker__trigger"
      severity="secondary"
      outlined
      size="small"
      :disabled="job === null"
      :loading="editor.loading === true"
      :aria-labelledby="`${labelId} ${id}-current`"
      aria-haspopup="listbox"
      :aria-expanded="listOpen"
      :aria-controls="listOpen ? listId : undefined"
      @click="toggleList"
    >
      <span :id="`${id}-current`" class="preset-picker__current" data-field="preset">{{
        current
      }}</span>
      <ChevronDown :size="16" aria-hidden="true" />
    </Button>
    <span v-if="missing" class="preset-picker__missing" data-state="missing">
      {{ t('presets.picker.missing') }}
    </span>
    <Button
      v-if="modified"
      class="preset-picker__modified"
      size="small"
      severity="warn"
      outlined
      :label="t('presets.picker.modified')"
      aria-haspopup="dialog"
      :aria-expanded="changesOpen"
      @click="toggleChanges"
    />
    <Button
      class="preset-picker__actions"
      size="small"
      text
      rounded
      :aria-label="t('presets.picker.actions')"
      aria-haspopup="menu"
      @click="toggleMenu"
    >
      <template #icon>
        <Ellipsis :size="18" aria-hidden="true" />
      </template>
    </Button>
    <Menu ref="actionsMenu" :model="menuItems" popup class="preset-picker__menu" />
    <Popover ref="listPopover" class="preset-picker__popover" @show="listShown" @hide="listHidden">
      <div :id="listId">
        <Listbox
          class="preset-picker__list"
          :model-value="presetId"
          :options="groups"
          option-label="label"
          option-value="value"
          option-group-label="label"
          option-group-children="items"
          filter
          :filter-placeholder="t('presets.picker.filter')"
          :ariaLabelledby="labelId"
          scroll-height="24rem"
          @update:model-value="choose"
        >
          <template #optiongroup="{ option }">
            <span class="preset-picker__group">{{ option.label }}</span>
          </template>
          <template #option="{ option }">
            <span class="preset-picker__option" :data-preset="option.value">
              <span>{{ option.label }}</span>
              <Lock
                v-if="option.builtIn"
                :size="12"
                class="preset-picker__icon"
                :aria-label="t('presets.builtIn')"
              />
              <Star
                v-if="option.isDefault"
                :size="12"
                class="preset-picker__icon preset-picker__icon--default"
                :aria-label="t('presets.default')"
              />
            </span>
          </template>
        </Listbox>
      </div>
    </Popover>
    <Popover
      ref="changesPopover"
      class="preset-picker__popover"
      @show="changesShown"
      @hide="changesOpen = false"
    >
      <section
        :id="changesId"
        class="preset-picker__changes"
        role="dialog"
        :aria-label="t('presets.changes.title', { name: current })"
      >
        <h2 class="preset-picker__changes-title">
          {{ t('presets.changes.title', { name: current }) }}
        </h2>
        <PresetChanges :changes="changes" :encoder="job?.video?.encoder ?? null" />
        <div class="preset-picker__changes-actions">
          <Button
            size="small"
            class="preset-picker__save-as"
            :label="t('presets.picker.saveAs')"
            :disabled="template === null"
            @click="openSaveAs"
          />
          <Button
            v-if="updatable !== null"
            size="small"
            severity="secondary"
            class="preset-picker__update"
            :label="t('presets.picker.update')"
            :loading="updating"
            @click="update"
          />
          <span v-else-if="preset?.built_in" class="preset-picker__locked">
            {{ t('presets.picker.builtInLocked') }}
          </span>
          <Button
            size="small"
            text
            class="preset-picker__open"
            :label="t('presets.picker.open')"
            @click="openPresets"
          />
        </div>
      </section>
    </Popover>
    <PresetNameDialog
      v-model:visible="saveAsOpen"
      :title="t('presets.picker.saveAsTitle')"
      :submit-label="t('presets.dialog.create')"
      :initial="saveAsInitial"
      :save="saveAs"
      @closed="saveAsClosed"
    />
  </div>
</template>

<style scoped>
.preset-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  min-width: 0;
}

.preset-picker__label {
  color: var(--rf-color-text-muted);
}

.preset-picker__trigger {
  min-width: 12rem;
  max-width: 22rem;
  justify-content: space-between;
}

.preset-picker__current {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preset-picker__list {
  width: min(22rem, 85vw);
  border: none;
}

.preset-picker__option {
  display: inline-flex;
  align-items: center;
  gap: var(--rf-space-1);
}

.preset-picker__icon {
  flex: none;
  color: var(--rf-color-text-muted);
}

.preset-picker__icon--default {
  color: var(--p-status-warn-color);
}

.preset-picker__group {
  font-weight: var(--rf-font-weight-bold);
}

.preset-picker__missing {
  color: var(--p-status-warn-color);
  font-size: var(--rf-font-size-sm);
}

.preset-picker__changes {
  display: grid;
  gap: var(--rf-space-3);
  max-width: min(32rem, 90vw);
  max-height: 60vh;
  overflow: auto;
}

.preset-picker__changes-title {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.preset-picker__changes-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.preset-picker__locked {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
