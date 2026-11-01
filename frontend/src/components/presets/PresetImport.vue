<script setup lang="ts">
import { Upload } from '@lucide/vue'
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import RadioButton from 'primevue/radiobutton'
import { computed, ref, shallowRef, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import { type ImportConflict, type PresetImportReport, usePresetsStore } from '@/stores/presets'

import { importClashes } from './format'

/**
 * *Import…*: a JSON file the user picks. When its presets clash with known ones (by id or
 * name), the user chooses rename, replace or skip first; the server's report is shown after.
 */
const emit = defineEmits<{ imported: [report: PresetImportReport] }>()

const { t } = useI18n()
const presets = usePresetsStore()
const id = useId()

const input = useTemplateRef<HTMLInputElement>('input')
const open = ref(false)
const file = shallowRef<File | null>(null)
const clashes = ref<string[]>([])
const policy = ref<ImportConflict>('rename')
const busy = ref(false)
const report = shallowRef<PresetImportReport | null>(null)
const failure = ref<string | null>(null)

const policies = computed<{ value: ImportConflict; label: string; help: string }[]>(() => [
  { value: 'rename', label: t('presets.import.rename'), help: t('presets.import.renameHelp') },
  { value: 'replace', label: t('presets.import.replace'), help: t('presets.import.replaceHelp') },
  { value: 'skip', label: t('presets.import.skip'), help: t('presets.import.skipHelp') },
])

function choose(): void {
  input.value?.click()
}

async function picked(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  const chosen = target.files?.[0] ?? null
  // The same file can be chosen again.
  target.value = ''
  if (chosen === null) return
  file.value = chosen
  report.value = null
  failure.value = null
  policy.value = 'rename'
  clashes.value = importClashes(await chosen.text(), presets.presets) ?? []
  open.value = true
  if (clashes.value.length === 0) await run()
}

async function run(): Promise<void> {
  if (file.value === null) return
  busy.value = true
  failure.value = null
  try {
    report.value = await presets.importFile(file.value, policy.value)
    emit('imported', report.value)
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    failure.value = error.problem.detail ?? error.problem.title
  } finally {
    busy.value = false
  }
}

const asking = computed(() => report.value === null && failure.value === null && !busy.value)
</script>

<template>
  <Button
    class="preset-import__button"
    size="small"
    severity="secondary"
    :label="t('presets.import.button')"
    @click="choose"
  >
    <template #icon><Upload :size="16" aria-hidden="true" /></template>
  </Button>
  <input
    ref="input"
    class="preset-import__input"
    type="file"
    accept=".json,application/json"
    hidden
    @change="picked"
  />
  <Dialog
    v-model:visible="open"
    modal
    :header="t('presets.import.title', { file: file?.name ?? '' })"
    class="preset-import"
    :style="{ width: 'min(34rem, 95vw)' }"
  >
    <div class="preset-import__body">
      <template v-if="asking && clashes.length > 0">
        <p class="preset-import__question">{{ t('presets.import.clashes', clashes.length) }}</p>
        <ul class="preset-import__names" data-list="clashes">
          <li v-for="name in clashes" :key="name">{{ name }}</li>
        </ul>
        <fieldset class="preset-import__policies">
          <legend class="rf-sr-only">{{ t('presets.import.policy') }}</legend>
          <div v-for="option in policies" :key="option.value" class="preset-import__policy">
            <RadioButton
              v-model="policy"
              :input-id="`${id}-${option.value}`"
              name="on-conflict"
              :value="option.value"
            />
            <label :for="`${id}-${option.value}`">
              <span class="preset-import__policy-label">{{ option.label }}</span>
              <span class="preset-import__policy-help">{{ option.help }}</span>
            </label>
          </div>
        </fieldset>
        <div class="preset-import__actions">
          <Button
            severity="secondary"
            text
            :label="t('presets.dialog.cancel')"
            @click="open = false"
          />
          <Button class="preset-import__run" :label="t('presets.import.run')" @click="run" />
        </div>
      </template>
      <p v-else-if="busy" class="preset-import__busy">{{ t('presets.import.busy') }}</p>
      <p v-else-if="failure" class="preset-import__failure" role="alert">{{ failure }}</p>
      <div v-else-if="report" class="preset-import__report" data-state="report" role="status">
        <p v-if="report.imported.length > 0">
          {{ t('presets.import.imported', report.imported.length) }}
        </p>
        <ul v-if="report.imported.length > 0" data-list="imported">
          <li v-for="preset in report.imported" :key="preset.id">{{ preset.name }}</li>
        </ul>
        <template v-if="report.renamed.length > 0">
          <p>{{ t('presets.import.renamed', report.renamed.length) }}</p>
          <ul data-list="renamed">
            <li v-for="item in report.renamed" :key="item.new_name">
              {{ t('presets.import.renamedItem', { name: item.name, newName: item.new_name }) }}
            </li>
          </ul>
        </template>
        <template v-if="report.replaced.length > 0">
          <p>{{ t('presets.import.replaced', report.replaced.length) }}</p>
          <ul data-list="replaced">
            <li v-for="name in report.replaced" :key="name">{{ name }}</li>
          </ul>
        </template>
        <template v-if="report.skipped.length > 0">
          <p>{{ t('presets.import.skipped', report.skipped.length) }}</p>
          <ul data-list="skipped">
            <li v-for="name in report.skipped" :key="name">{{ name }}</li>
          </ul>
        </template>
        <ul v-if="report.issues.length > 0" class="preset-import__issues" data-list="issues">
          <li v-for="(issue, index) in report.issues" :key="index">{{ issue.message }}</li>
        </ul>
        <p v-if="report.imported.length === 0 && report.skipped.length === 0">
          {{ t('presets.import.nothing') }}
        </p>
      </div>
      <div v-if="!asking" class="preset-import__actions">
        <Button
          class="preset-import__close"
          :label="t('presets.import.close')"
          :disabled="busy"
          @click="open = false"
        />
      </div>
    </div>
  </Dialog>
</template>

<style scoped>
.preset-import__body {
  display: grid;
  gap: var(--rf-space-3);
}

.preset-import__body p,
.preset-import__body ul {
  margin: 0;
}

.preset-import__policies {
  display: grid;
  gap: var(--rf-space-2);
  margin: 0;
  padding: 0;
  border: none;
}

.preset-import__policy {
  display: flex;
  align-items: flex-start;
  gap: var(--rf-space-2);
}

.preset-import__policy label {
  display: grid;
}

.preset-import__policy-label {
  font-weight: var(--rf-font-weight-medium);
}

.preset-import__policy-help {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.preset-import__failure {
  color: var(--p-status-error-color);
}

.preset-import__issues {
  color: var(--p-status-warn-color);
}

.preset-import__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--rf-space-2);
}
</style>
