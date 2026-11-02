<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { DimensionSettings } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'

type Size = NonNullable<DimensionSettings['size']>
type SizeMode = Size['mode']

const { t } = useI18n()
const editor = useEditorStore()
const crop = useCropStore()
const boxId = useId()

/** The boxes of *Fit within*, all 16:9 like their names' sources. */
const BOXES = [
  { id: '2160p', width: 3840, height: 2160 },
  { id: '1440p', width: 2560, height: 1440 },
  { id: '1080p', width: 1920, height: 1080 },
  { id: '720p', width: 1280, height: 720 },
  { id: '576p', width: 1024, height: 576 },
  { id: '480p', width: 854, height: 480 },
]
const CUSTOM = 'custom'

const size = computed<Size | null>(() => editor.job?.dimensions?.size ?? null)
const MODES: SizeMode[] = ['source', 'fit', 'width', 'height']
const modes = computed(() =>
  MODES.map((value) => ({ value, label: t(`dimensions.size.modes.${value}`) })),
)
const boxes = computed(() => [
  ...BOXES.map((box) => ({ value: box.id, label: `${box.id} (${box.width}×${box.height})` })),
  { value: CUSTOM, label: t('dimensions.size.custom') },
])

// *Custom* stays chosen while its values happen to match a named box.
const customChosen = ref(false)
watch(
  () => editor.session,
  () => {
    customChosen.value = false
  },
)
const box = computed(() => {
  const current = size.value
  if (current?.mode !== 'fit') return null
  if (customChosen.value) return CUSTOM
  return (
    BOXES.find((named) => named.width === current.width && named.height === current.height)?.id ??
    CUSTOM
  )
})

function setMode(mode: unknown): void {
  if (mode === size.value?.mode) return
  const output = crop.geometry?.geometry ?? null
  customChosen.value = false
  switch (mode as SizeMode) {
    case 'source':
      editor.set('/dimensions/size', { mode: 'source' })
      break
    case 'fit':
      editor.set('/dimensions/size', { mode: 'fit', width: 1920, height: 1080 })
      break
    case 'width':
      editor.set('/dimensions/size', { mode: 'width', width: output?.scaled_width ?? 1920 })
      break
    case 'height':
      editor.set('/dimensions/size', { mode: 'height', height: output?.scaled_height ?? 1080 })
      break
  }
}

function setBox(id: unknown): void {
  if (id === CUSTOM) {
    customChosen.value = true
    return
  }
  customChosen.value = false
  const named = BOXES.find((candidate) => candidate.id === id)
  if (named)
    editor.set('/dimensions/size', { mode: 'fit', width: named.width, height: named.height })
}

function setNumber(pointer: string, value: number | null | undefined): void {
  if (typeof value === 'number' && value !== editor.get(pointer)) {
    editor.set(pointer, value, { coalesce: pointer })
  }
}
</script>

<template>
  <div v-if="size !== null" class="size-section">
    <Field
      :label="t('dimensions.size.mode')"
      path="dimensions.size"
      :help="t('dimensions.size.modeHelp')"
    >
      <template #default="{ id, labelId, invalid }">
        <div class="size-section__row">
          <Select
            :input-id="id"
            :model-value="size.mode"
            :options="modes"
            option-label="label"
            option-value="value"
            :ariaLabelledby="labelId"
            :invalid="invalid"
            data-control="size-mode"
            @update:model-value="setMode"
          />
          <Select
            v-if="size.mode === 'fit'"
            :input-id="boxId"
            :model-value="box"
            :options="boxes"
            option-label="label"
            option-value="value"
            :ariaLabel="t('dimensions.size.box')"
            data-control="size-box"
            @update:model-value="setBox"
          />
          <template v-if="size.mode === 'fit' && box === CUSTOM">
            <InputNumber
              :model-value="size.width"
              :min="1"
              :use-grouping="false"
              :ariaLabel="t('dimensions.size.width')"
              :invalid="invalid"
              data-input="width"
              @update:model-value="setNumber('/dimensions/size/width', $event)"
            />
            <span aria-hidden="true">×</span>
            <InputNumber
              :model-value="size.height"
              :min="1"
              :use-grouping="false"
              :ariaLabel="t('dimensions.size.height')"
              :invalid="invalid"
              data-input="height"
              @update:model-value="setNumber('/dimensions/size/height', $event)"
            />
          </template>
          <InputNumber
            v-else-if="size.mode === 'width'"
            :model-value="size.width"
            :min="1"
            :use-grouping="false"
            :ariaLabel="t('dimensions.size.width')"
            :invalid="invalid"
            data-input="width"
            @update:model-value="setNumber('/dimensions/size/width', $event)"
          />
          <InputNumber
            v-else-if="size.mode === 'height'"
            :model-value="size.height"
            :min="1"
            :use-grouping="false"
            :ariaLabel="t('dimensions.size.height')"
            :invalid="invalid"
            data-input="height"
            @update:model-value="setNumber('/dimensions/size/height', $event)"
          />
        </div>
      </template>
    </Field>
    <Field
      :label="t('dimensions.size.upscale')"
      path="dimensions.allow_upscaling"
      :help="t('dimensions.size.upscaleHelp')"
    >
      <template #default="{ id, labelId }">
        <ToggleSwitch
          :input-id="id"
          :model-value="editor.job?.dimensions?.allow_upscaling ?? false"
          :ariaLabelledby="labelId"
          data-control="upscale"
          @update:model-value="editor.set('/dimensions/allow_upscaling', $event)"
        />
      </template>
    </Field>
  </div>
</template>

<style scoped>
.size-section {
  display: grid;
  gap: var(--rf-space-3);
}

.size-section__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
}

.size-section__row :deep(.p-inputnumber-input) {
  width: 6rem;
}
</style>
