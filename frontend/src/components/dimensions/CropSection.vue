<script setup lang="ts">
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import SelectButton from 'primevue/selectbutton'
import { computed, nextTick, reactive, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { CropRect } from '@/api/types'
import Field from '@/components/base/Field.vue'
import CropMagnifier from '@/components/crop/CropMagnifier.vue'
import { type CropMode, useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'

import { EDGES, type Edge, NO_CROP } from './grid'

const { t } = useI18n()
const crop = useCropStore()
const editor = useEditorStore()
const inputId = useId()

const MODES: CropMode[] = ['auto', 'conservative', 'none', 'manual']
const modes = computed(() =>
  MODES.map((value) => ({ value, label: t(`dimensions.crop.modes.${value}`) })),
)

const shown = computed<CropRect>(() => crop.rect ?? NO_CROP)
const inGroup = computed(() => editor.target?.kind === 'group')

function values(rect: CropRect) {
  return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right }
}

const detectionLine = computed(() => {
  const found = crop.detection
  if (found === null) return null
  switch (crop.mode) {
    case 'auto':
      return t('dimensions.detection.auto', {
        ...values(found.auto),
        frames: found.auto_frames,
        total: found.samples.length,
      })
    case 'conservative':
      return t('dimensions.detection.conservative', {
        ...values(found.conservative),
        total: found.samples.length,
      })
    default:
      return null
  }
})

const detectedMode = computed(() => crop.mode === 'auto' || crop.mode === 'conservative')

function setMode(mode: unknown): void {
  void crop.setMode(mode as CropMode)
}

// What the inputs show: typed text until it is committed, then the stored (snapped) value.
const drafts = reactive<Record<Edge, string>>({ top: '0', bottom: '0', left: '0', right: '0' })
watch(
  shown,
  (rect) => {
    for (const edge of EDGES) drafts[edge] = String(rect[edge])
  },
  { immediate: true },
)

async function commit(edge: Edge): Promise<void> {
  const value = Number.parseInt(drafts[edge], 10)
  if (!Number.isNaN(value)) {
    crop.setRect({ ...shown.value, [edge]: value }, { coalesce: `dimensions.crop.${edge}` })
  }
  // Let the typed text render first: when snapping keeps the stored value, only a change of the
  // input's value replaces the typed text with it.
  await nextTick()
  drafts[edge] = String(shown.value[edge])
}

function stepOf(edge: Edge): number | undefined {
  const grid = crop.grid
  if (grid === null) return undefined
  return edge === 'top' || edge === 'bottom' ? grid.stepY : grid.stepX
}

function redetect(): void {
  crop.detect().catch(() => {})
}
</script>

<template>
  <div class="crop-section">
    <Field
      :label="t('dimensions.crop.mode')"
      path="dimensions.crop"
      :help="t('dimensions.crop.modeHelp')"
    >
      <template #default="{ id, labelId }">
        <SelectButton
          :pt="{ root: { id } }"
          :model-value="crop.mode"
          :options="modes"
          option-label="label"
          option-value="value"
          :allow-empty="false"
          :ariaLabelledby="labelId"
          data-control="crop-mode"
          @update:model-value="setMode"
        />
      </template>
    </Field>

    <div v-if="detectedMode" class="crop-section__detection" aria-live="polite" data-detection>
      <p v-if="crop.detecting" class="crop-section__line">
        {{ t('dimensions.detection.running') }}
      </p>
      <p
        v-else-if="crop.detectionError !== null"
        class="crop-section__line crop-section__line--error"
      >
        {{ t('dimensions.detection.failed', { reason: crop.detectionError }) }}
        <Button
          :label="t('dimensions.detection.again')"
          size="small"
          severity="secondary"
          data-action="detect-again"
          @click="redetect"
        />
      </p>
      <template v-else-if="detectionLine !== null">
        <p class="crop-section__line" data-line="detection">{{ detectionLine }}</p>
        <ul v-if="(crop.detection?.notes ?? []).length > 0" class="crop-section__notes">
          <li v-for="note in crop.detection?.notes" :key="note">{{ note }}</li>
        </ul>
      </template>
      <p v-if="inGroup" class="crop-section__hint">{{ t('dimensions.detection.group') }}</p>
    </div>

    <template v-if="crop.editable">
      <Field :label="t('dimensions.crop.values')" path="dimensions.crop.rect">
        <template #default="{ id, invalid }">
          <div class="crop-section__edges">
            <div v-for="(edge, index) in EDGES" :key="edge" class="crop-section__edge">
              <label :for="index === 0 ? id : `${inputId}-${edge}`">
                {{ t(`dimensions.crop.edges.${edge}`) }}
              </label>
              <InputText
                :id="index === 0 ? id : `${inputId}-${edge}`"
                type="number"
                inputmode="numeric"
                min="0"
                :step="stepOf(edge)"
                :model-value="drafts[edge]"
                :invalid="invalid"
                :data-edge="edge"
                @update:model-value="drafts[edge] = $event ?? ''"
                @change="commit(edge)"
              />
            </div>
          </div>
        </template>
      </Field>
      <p
        v-if="crop.snapNote !== null"
        class="crop-section__snap"
        aria-live="polite"
        data-note="snap"
      >
        {{ crop.snapNote }}
      </p>
      <CropMagnifier />
    </template>
  </div>
</template>

<style scoped>
.crop-section {
  display: grid;
  gap: var(--rf-space-3);
}

.crop-section__detection {
  display: grid;
  gap: var(--rf-space-1);
}

.crop-section__line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2);
  margin: 0;
  font-family: var(--rf-font-mono);
  font-size: var(--rf-font-size-sm);
}

.crop-section__line--error {
  color: var(--p-status-error-color);
  font-family: inherit;
}

.crop-section__notes {
  margin: 0;
  padding-left: var(--rf-space-4);
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.crop-section__hint,
.crop-section__snap {
  margin: 0;
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-sm);
}

.crop-section__edges {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(6.5rem, 1fr));
  gap: var(--rf-space-2) var(--rf-space-3);
}

.crop-section__edge {
  display: grid;
  gap: var(--rf-space-1);
  font-size: var(--rf-font-size-sm);
}

.crop-section__edge :deep(input) {
  width: 100%;
}
</style>
