<script setup lang="ts">
import Button from 'primevue/button'
import InputNumber from 'primevue/inputnumber'
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { api, ApiError, unwrap } from '@/api/client'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import { formatBytes } from '@/components/summary/format'

import { type SettingControl, useSetting, useSettingsLocked } from './useSetting'

const { t } = useI18n()
const locked = useSettingsLocked()

const sampleFrames = useSetting<number>('/preview/sample_frames')
const cacheLimit = useSetting<number>('/preview/cache_size_mb')

/** Bytes of cached frames and clips; `null` until the server has answered. */
const cacheSize = ref<number | null>(null)
const freed = ref<number | null>(null)
const clearing = ref(false)

async function readSize(): Promise<void> {
  try {
    cacheSize.value = unwrap(await api.GET('/api/preview/cache')).size
  } catch (error) {
    // The API client has shown it as a toast.
    if (!(error instanceof ApiError)) throw error
  }
}

async function clearCache(): Promise<void> {
  clearing.value = true
  try {
    freed.value = unwrap(await api.DELETE('/api/preview/cache')).freed
    await readSize()
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
  } finally {
    clearing.value = false
  }
}

onMounted(readSize)

// An emptied field keeps the saved number. Tab sends the value and the blur right after it sends
// it again, before the first save has been answered.
function numberSaver(control: SettingControl<number>): (value: number | null) => Promise<void> {
  let saving: number | null = null
  return async (value) => {
    if (value === null || value === control.value.value || value === saving) return
    saving = value
    await control.save(value)
    if (saving === value) saving = null
  }
}
const saveSampleFrames = numberSaver(sampleFrames)
const saveCacheLimit = numberSaver(cacheLimit)
</script>

<template>
  <Section :title="t('settings.preview.title')">
    <div class="preview-section__fields">
      <Field
        :label="t('settings.preview.sampleFrames')"
        :help="t('settings.preview.sampleFramesHelp')"
        :issues="sampleFrames.issues.value"
      >
        <template #default="{ id, invalid }">
          <InputNumber
            :input-id="id"
            :model-value="sampleFrames.value.value ?? null"
            :min="1"
            :max="60"
            :use-grouping="false"
            :input-style="{ width: '6rem' }"
            show-buttons
            :invalid="invalid"
            :disabled="locked"
            data-field="sample-frames"
            @update:model-value="saveSampleFrames"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.preview.cacheLimit')"
        :help="t('settings.preview.cacheLimitHelp')"
        :issues="cacheLimit.issues.value"
      >
        <template #default="{ id, invalid }">
          <InputNumber
            :input-id="id"
            :model-value="cacheLimit.value.value ?? null"
            :min="0"
            :use-grouping="false"
            :suffix="t('settings.preview.mebibytes')"
            :input-style="{ width: '8rem' }"
            :invalid="invalid"
            :disabled="locked"
            data-field="cache-limit"
            @update:model-value="saveCacheLimit"
          />
        </template>
      </Field>
      <div class="preview-section__cache">
        <p class="preview-section__size" data-field="cache-size" aria-live="polite">
          {{
            cacheSize === null
              ? t('settings.preview.sizeUnknown')
              : t('settings.preview.size', { size: formatBytes(cacheSize, t) })
          }}
        </p>
        <Button
          :label="t('settings.preview.clear')"
          severity="secondary"
          outlined
          size="small"
          :loading="clearing"
          data-action="clear-cache"
          @click="clearCache"
        />
        <p
          v-if="freed !== null"
          class="preview-section__freed"
          data-field="freed"
          aria-live="polite"
        >
          {{ t('settings.preview.freed', { size: formatBytes(freed, t) }) }}
        </p>
      </div>
    </div>
  </Section>
</template>

<style scoped>
.preview-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}

.preview-section__cache {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-3);
}

.preview-section__size,
.preview-section__freed {
  margin: 0;
}

.preview-section__freed {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}
</style>
