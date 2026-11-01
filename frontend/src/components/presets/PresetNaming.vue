<script setup lang="ts">
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, onBeforeUnmount, ref, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { NamingOptions, Preset } from '@/api/types'
import NamingOptionsEditor from '@/components/naming/NamingOptionsEditor.vue'
import { usePresetsStore } from '@/stores/presets'
import { useSettingsStore } from '@/stores/settings'
import { useSourcesStore } from '@/stores/sources'

import { NAMING_SAVE_DELAY } from './format'

/** What `NamingOptions` are when Settings → Output are not known (the model's defaults). */
const DEFAULT_NAMING: NamingOptions = {
  movie_template: '{main_title}',
  episode_template: '{main_title}',
  name_source: 'auto',
  word_separator: 'keep',
  title_case: false,
  replace_underscores: false,
  remove_punctuation: false,
  mp4_extension: 'mp4',
  output_folder_mode: 'same_as_source',
  output_folder: null,
}

/**
 * A preset's naming: its own options, or `null` for Settings → Output's (the switch). Edits are
 * saved 600 ms after the last one, and at once when the preset changes or this closes.
 */
const props = defineProps<{ preset: Preset }>()

const { t } = useI18n()
const presets = usePresetsStore()
const settings = useSettingsStore()
const sources = useSourcesStore()
const switchId = `${useId()}-inherit`

const inherited = computed<NamingOptions>(() => settings.settings?.output?.naming ?? DEFAULT_NAMING)
/** The naming the editor shows; `null`: Settings → Output's. Ahead of the preset while edits wait. */
const draft = shallowRef<NamingOptions | null>(props.preset.naming ?? null)
const failure = ref<string | null>(null)
const saving = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let pending: { id: string; naming: NamingOptions | null } | null = null

const sourceIds = computed(() => sources.entries.map((entry) => entry.id))
const container = computed(() => props.preset.output?.container ?? 'mkv')
const shown = computed(() => draft.value ?? inherited.value)

async function flush(): Promise<void> {
  clearTimeout(timer)
  timer = undefined
  const change = pending
  pending = null
  if (change === null) return
  const current = presets.byId(change.id)
  if (current === undefined || current.built_in) return
  saving.value = true
  try {
    await presets.save({ ...current, naming: change.naming })
    failure.value = null
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    failure.value = error.problem.detail ?? error.problem.title
  } finally {
    saving.value = false
  }
}

function schedule(naming: NamingOptions | null, delay: number): void {
  draft.value = naming
  pending = { id: props.preset.id, naming }
  clearTimeout(timer)
  if (delay === 0) void flush()
  else timer = setTimeout(() => void flush(), delay)
}

function edit(naming: NamingOptions): void {
  schedule(naming, NAMING_SAVE_DELAY)
}

function setInherit(inherit: boolean): void {
  schedule(inherit ? null : { ...inherited.value }, 0)
}

// Another preset: what waits for the last one is saved first.
watch(
  () => props.preset.id,
  () => {
    void flush()
    draft.value = props.preset.naming ?? null
    failure.value = null
  },
)
// The saved preset (or one changed elsewhere) while nothing waits.
watch(
  () => props.preset.naming,
  (naming) => {
    if (pending === null && !saving.value) draft.value = naming ?? null
  },
)

onBeforeUnmount(() => void flush())
</script>

<template>
  <div class="preset-naming" data-section="naming">
    <div class="preset-naming__inherit">
      <ToggleSwitch
        :input-id="switchId"
        class="preset-naming__switch"
        :model-value="draft === null"
        :disabled="preset.built_in"
        @update:model-value="setInherit"
      />
      <label :for="switchId">{{ t('presets.naming.inherit') }}</label>
      <span v-if="saving" class="preset-naming__status">{{ t('presets.naming.saving') }}</span>
    </div>
    <p v-if="draft === null" class="preset-naming__note">
      {{ t('presets.naming.inheritNote') }}
    </p>
    <p v-if="failure" class="preset-naming__failure" role="alert">{{ failure }}</p>
    <NamingOptionsEditor
      :model-value="shown"
      :source-ids="sourceIds"
      :container="container"
      :disabled="preset.built_in || draft === null"
      compact
      @update:model-value="edit"
    />
  </div>
</template>

<style scoped>
.preset-naming {
  display: grid;
  gap: var(--rf-space-3);
}

.preset-naming__inherit {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.preset-naming__status,
.preset-naming__note {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.preset-naming__failure {
  margin: 0;
  color: var(--p-status-error-color);
}
</style>
