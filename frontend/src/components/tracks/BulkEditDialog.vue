<script setup lang="ts">
import Button from 'primevue/button'
import Checkbox from 'primevue/checkbox'
import Dialog from 'primevue/dialog'
import SelectButton from 'primevue/selectbutton'
import { computed, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Container } from '@/components/language/catalog'
import LanguagePicker from '@/components/language/LanguagePicker.vue'
import { useEditorStore } from '@/stores/editor'

import { bulkOps, type Flag, FLAGS, type MetadataChanges } from './metadata'

/**
 * Language and flags for several output tracks of a list at once: only what is set here is
 * changed, every track in one undo step.
 */
const props = defineProps<{
  list: 'audio' | 'subtitles'
  /** The selected tracks' places in the list. */
  indexes: readonly number[]
}>()

const visible = defineModel<boolean>('visible', { required: true })
const emit = defineEmits<{ applied: []; closed: [] }>()

const { t } = useI18n()
const editor = useEditorStore()
const id = useId()

type FlagState = 'leave' | 'on' | 'off'

const setLanguage = ref(false)
const language = ref<string | null>(null)
const flags = reactive<Record<Flag, FlagState>>(
  Object.fromEntries(FLAGS.map((flag) => [flag, 'leave'])) as Record<Flag, FlagState>,
)

// Every opening starts from "change nothing".
watch(visible, (shown) => {
  if (!shown) return
  setLanguage.value = false
  language.value = null
  for (const flag of FLAGS) flags[flag] = 'leave'
})

const container = computed<Container | undefined>(() => {
  const value = editor.job?.output?.container
  return value === 'mkv' || value === 'mp4' || value === 'webm' ? value : undefined
})

const stateOptions = computed(() => [
  { value: 'leave', label: t('tracks.bulk.leave') },
  { value: 'on', label: t('tracks.bulk.on') },
  { value: 'off', label: t('tracks.bulk.off') },
])

const changes = computed<MetadataChanges>(() => {
  const result: MetadataChanges = {}
  if (setLanguage.value) result.language = language.value
  for (const flag of FLAGS) {
    if (flags[flag] !== 'leave') result[flag] = flags[flag] === 'on'
  }
  return result
})
const changesSomething = computed(() => Object.keys(changes.value).length > 0)

function apply(): void {
  const tracks = (props.list === 'audio' ? editor.job?.audio : editor.job?.subtitles) ?? []
  const ops = bulkOps(props.list, tracks, props.indexes, changes.value)
  if (ops.length > 0) editor.patch(ops)
  visible.value = false
  emit('applied')
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    class="bulk-edit"
    :header="t('tracks.bulk.title', { count: indexes.length }, indexes.length)"
    :style="{ width: 'min(36rem, calc(100vw - 2rem))' }"
    data-dialog="bulk-edit"
    @after-hide="emit('closed')"
  >
    <div class="bulk-edit__body">
      <p class="bulk-edit__intro">{{ t('tracks.bulk.intro') }}</p>
      <div class="bulk-edit__language">
        <div class="bulk-edit__check">
          <Checkbox v-model="setLanguage" :input-id="`${id}-set-language`" binary />
          <label :for="`${id}-set-language`">{{ t('tracks.bulk.setLanguage') }}</label>
        </div>
        <span :id="`${id}-language`" class="rf-sr-only">{{ t('tracks.bulk.language') }}</span>
        <LanguagePicker
          v-model="language"
          :labelledby="`${id}-language`"
          :disabled="!setLanguage"
          :container="container"
          :none-label="t('tracks.metadata.keepLanguage')"
          clearable
          data-role="bulk-language"
        />
      </div>
      <div class="bulk-edit__flags" role="group" :aria-label="t('tracks.metadata.flags')">
        <div v-for="flag in FLAGS" :key="flag" class="bulk-edit__flag" :data-flag="flag">
          <span :id="`${id}-${flag}`" class="bulk-edit__flag-label">
            {{ t(`tracks.metadata.flag.${flag}`) }}
          </span>
          <SelectButton
            v-model="flags[flag]"
            :options="stateOptions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :ariaLabelledby="`${id}-${flag}`"
            size="small"
          />
        </div>
      </div>
    </div>
    <template #footer>
      <Button
        severity="secondary"
        text
        :label="t('tracks.bulk.cancel')"
        data-action="bulk-cancel"
        @click="visible = false"
      />
      <Button
        :label="t('tracks.bulk.apply')"
        :disabled="!changesSomething"
        data-action="bulk-apply"
        @click="apply"
      />
    </template>
  </Dialog>
</template>

<style scoped>
.bulk-edit__body {
  display: grid;
  gap: var(--rf-space-4);
}

.bulk-edit__intro {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.bulk-edit__language {
  display: grid;
  gap: var(--rf-space-2);
}

.bulk-edit__check {
  display: flex;
  align-items: center;
  gap: var(--rf-space-2);
}

.bulk-edit__flags {
  display: grid;
  gap: var(--rf-space-2);
}

.bulk-edit__flag {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--rf-space-2);
}

.bulk-edit__flag-label {
  font-weight: var(--rf-font-weight-medium);
}
</style>
