<script setup lang="ts">
import { Download } from '@lucide/vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import { computed, nextTick, onMounted, ref, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/client'
import type { Preset } from '@/api/types'
import { download, exportFileName } from '@/components/presets/format'
import PresetDetails from '@/components/presets/PresetDetails.vue'
import PresetImport from '@/components/presets/PresetImport.vue'
import PresetNameDialog, {
  type PresetDetailsInput,
} from '@/components/presets/PresetNameDialog.vue'
import PresetTree from '@/components/presets/PresetTree.vue'
import FocusSafeButton from '@/components/shell/FocusSafeButton'
import { focusLost, focusWorkspace } from '@/components/shell/focus'
import { useEditorStore } from '@/stores/editor'
import {
  type PresetImportReport,
  suggestedName,
  templateOfPreset,
  usePresetsStore,
} from '@/stores/presets'
import { useToastStore } from '@/stores/toasts'

const { t } = useI18n()
const presets = usePresetsStore()
const editor = useEditorStore()
const toasts = useToastStore()
const route = useRoute()
const router = useRouter()

const chosen = ref<string | null>(
  typeof route.query.preset === 'string' ? route.query.preset : null,
)
const busy = ref(false)
const renaming = ref<Preset | null>(null)
/** The preset a confirmation is open for, and what it confirms. */
const confirming = ref<{ preset: Preset; action: 'remove' | 'update' } | null>(null)
const tree = useTemplateRef<InstanceType<typeof PresetTree>>('tree')

onMounted(() => void presets.load().catch(() => undefined))

/** The chosen preset, else the job's, else the default, else the first. */
const selected = computed<Preset | null>(() => {
  for (const id of [chosen.value, editor.presetId, presets.defaultId]) {
    const preset = id === null ? undefined : presets.byId(id)
    if (preset !== undefined) return preset
  }
  return presets.categories[0]?.presets[0] ?? null
})

const userPresets = computed(() => presets.presets.filter((preset) => !preset.built_in))

function toastFailure(summary: string, error: unknown): void {
  if (!(error instanceof ApiError)) throw error
  toasts.push({
    severity: 'error',
    summary,
    detail: error.problem.detail ?? error.problem.title,
    life: 10_000,
  })
}

/** Runs one change at a time; the store's own failures are toasts already, others are shown here. */
async function act(run: () => Promise<void>, failure?: string): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    await run()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    if (failure !== undefined) toastFailure(failure, error)
  } finally {
    busy.value = false
  }
}

function apply(id: string): Promise<void> {
  if (editor.job === null) return Promise.resolve()
  return act(async () => {
    await editor.applyPreset(id)
    await router.push({ name: 'workspace' })
    await nextTick()
    focusWorkspace()
  })
}

function duplicate(preset: Preset): Promise<void> {
  return act(
    async () => {
      const request = {
        template: templateOfPreset(preset),
        name: preset.name,
        category: preset.built_in ? 'Custom' : preset.category,
        description: preset.description,
      }
      let created: Preset
      try {
        created = await presets.create(request)
      } catch (error) {
        // The copy takes the free name the server offers (*Name (2)*).
        const free = suggestedName(error)
        if (free === null) throw error
        created = await presets.create({ ...request, name: free })
      }
      chosen.value = created.id
      // The details of the copy replace the button.
      await tree.value?.focusPreset(created.id)
    },
    t('presets.view.duplicateFailed', { name: preset.name }),
  )
}

async function rename(details: PresetDetailsInput): Promise<void> {
  const preset = renaming.value
  if (preset === null) return
  await presets.save({ ...preset, ...details })
}

function update(preset: Preset): Promise<void> {
  const template = editor.currentTemplate
  if (template === null) return Promise.resolve()
  return act(
    async () => {
      await presets.save({
        ...template,
        id: preset.id,
        name: preset.name,
        category: preset.category,
        description: preset.description,
        built_in: false,
      })
      editor.refreshPresetChanges()
      toasts.push({
        severity: 'success',
        summary: t('presets.picker.updated', { name: preset.name }),
        life: 5000,
      })
    },
    t('presets.picker.updateFailed', { name: preset.name }),
  )
}

/** Updating the open job's own preset needs no confirmation; any other one does. */
function askUpdate(preset: Preset): void {
  if (preset.id === editor.presetId) void update(preset)
  else confirming.value = { preset, action: 'update' }
}

function askRemove(id: string): void {
  const preset = presets.byId(id)
  if (preset !== undefined && !preset.built_in) confirming.value = { preset, action: 'remove' }
}

function remove(preset: Preset): Promise<void> {
  return act(async () => {
    await presets.remove(preset.id)
    if (chosen.value === preset.id) chosen.value = null
    await nextTick()
    await refocusTree()
  })
}

/**
 * The confirmation gives the focus back to the control that opened it: after a deletion, that
 * control is gone, whether the dialog closes before the answer comes or after it.
 */
async function refocusTree(): Promise<void> {
  if (focusLost() && selected.value !== null) await tree.value?.focusPreset(selected.value.id)
}

async function confirm(): Promise<void> {
  const pending = confirming.value
  confirming.value = null
  if (pending === null) return
  if (pending.action === 'remove') await remove(pending.preset)
  else await update(pending.preset)
}

function makeDefault(preset: Preset): Promise<void> {
  return act(() => presets.setDefault(preset.id))
}

function exportPresets(list: Preset[]): Promise<void> {
  return act(async () => {
    const blob = await presets.exportPresets(list.map((preset) => preset.id))
    download(blob, exportFileName(list))
  })
}

function imported(report: PresetImportReport): void {
  const first = report.imported[0]
  if (first !== undefined) chosen.value = first.id
}

const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})
const renameOpen = computed({
  get: () => renaming.value !== null,
  set: (open: boolean) => {
    if (!open) renaming.value = null
  },
})
const renameInitial = computed<PresetDetailsInput>(() => ({
  name: renaming.value?.name ?? '',
  category: renaming.value?.category ?? '',
  description: renaming.value?.description ?? '',
}))
</script>

<template>
  <main class="view presets-view" data-view="presets">
    <header class="presets-view__header">
      <h1 class="presets-view__title">{{ t('presets.view.title') }}</h1>
      <div class="presets-view__tools">
        <PresetImport @imported="imported" />
        <FocusSafeButton
          class="presets-view__export-all"
          size="small"
          severity="secondary"
          :label="t('presets.view.exportAll')"
          :disabled="userPresets.length === 0 || busy"
          @click="exportPresets(userPresets)"
        >
          <template #icon><Download :size="16" aria-hidden="true" /></template>
        </FocusSafeButton>
      </div>
    </header>
    <p v-if="!presets.loaded" class="presets-view__loading">{{ t('presets.view.loading') }}</p>
    <div v-else class="presets-view__body">
      <div class="presets-view__tree">
        <PresetTree
          ref="tree"
          :categories="presets.categories"
          :selected-id="selected?.id ?? null"
          :default-id="presets.defaultId"
          :current-id="editor.presetId"
          @select="chosen = $event"
          @apply="apply"
          @remove="askRemove"
        />
        <p class="presets-view__keys">{{ t('presets.tree.keys') }}</p>
      </div>
      <section class="presets-view__details">
        <PresetDetails
          v-if="selected"
          :key="selected.id"
          :preset="selected"
          :is-default="selected.id === presets.defaultId"
          :can-apply="editor.job !== null"
          :can-update="editor.currentTemplate !== null"
          :busy="busy"
          @apply="apply(selected.id)"
          @duplicate="duplicate(selected)"
          @rename="renaming = selected"
          @update="askUpdate(selected)"
          @remove="askRemove(selected.id)"
          @make-default="makeDefault(selected)"
          @export="exportPresets([selected])"
        />
      </section>
    </div>
    <PresetNameDialog
      v-model:visible="renameOpen"
      :title="t('presets.view.renameTitle')"
      :submit-label="t('presets.dialog.save')"
      :initial="renameInitial"
      :save="rename"
    />
    <Dialog
      v-model:visible="confirmOpen"
      modal
      :header="
        confirming?.action === 'update'
          ? t('presets.view.confirmUpdateTitle')
          : t('presets.view.confirmRemoveTitle')
      "
      class="presets-view__confirm"
      :style="{ width: 'min(28rem, 95vw)' }"
      @after-hide="refocusTree"
    >
      <p v-if="confirming?.action === 'update'" class="presets-view__confirm-text">
        {{ t('presets.view.confirmUpdate', { name: confirming.preset.name }) }}
      </p>
      <p v-else-if="confirming" class="presets-view__confirm-text">
        {{ t('presets.view.confirmRemove', { name: confirming.preset.name }) }}
      </p>
      <template #footer>
        <Button
          severity="secondary"
          text
          :label="t('presets.dialog.cancel')"
          autofocus
          @click="confirmOpen = false"
        />
        <Button
          class="presets-view__confirm-button"
          :severity="confirming?.action === 'update' ? undefined : 'danger'"
          :label="
            confirming?.action === 'update'
              ? t('presets.details.update')
              : t('presets.details.delete')
          "
          @click="confirm"
        />
      </template>
    </Dialog>
  </main>
</template>

<style scoped>
.presets-view {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-4);
  min-width: 0;
  padding: var(--rf-space-4);
  overflow: clip;
}

.presets-view__header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--rf-space-3);
}

.presets-view__title {
  margin: 0;
  font-size: var(--rf-text-title);
  line-height: var(--rf-line-height-tight);
}

.presets-view__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.presets-view__body {
  display: grid;
  flex: 1;
  grid-template-columns: minmax(16rem, 22rem) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  gap: var(--rf-space-4);
  min-height: 0;
}

/* Positioned: screen-reader-only text inside stays in the scrolled box, not below the page. */
.presets-view__tree,
.presets-view__details {
  position: relative;
  min-height: 0;
  overflow: auto;
}

.presets-view__tree {
  padding-right: var(--rf-space-2);
  border-right: 1px solid var(--rf-color-border);
}

.presets-view__keys,
.presets-view__loading {
  margin: var(--rf-space-3) 0 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.presets-view__confirm-text {
  margin: 0;
}

@media (width < 60rem) {
  .presets-view {
    height: auto;
    overflow: visible;
  }

  .presets-view__body {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
  }

  .presets-view__tree {
    border-right: none;
  }
}
</style>
