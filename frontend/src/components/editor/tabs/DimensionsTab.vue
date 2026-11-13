<script setup lang="ts">
import InputNumber from 'primevue/inputnumber'
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { DimensionSettings } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import CropSection from '@/components/dimensions/CropSection.vue'
import PipelineHeader from '@/components/dimensions/PipelineHeader.vue'
import SizeSection from '@/components/dimensions/SizeSection.vue'
import { useReveal } from '@/composables/useReveal'
import { useCropStore } from '@/stores/crop'
import { useEditorStore } from '@/stores/editor'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const crop = useCropStore()
const editor = useEditorStore()
const ui = useUiStore()
const root = useTemplateRef<HTMLElement>('root')

useReveal('dimensions', root)

const dimensions = computed<DimensionSettings | null>(() => editor.job?.dimensions ?? null)
const locked = computed(() => !crop.pictureEditable)
const lockedNote = computed(() =>
  editor.job?.video?.passthrough
    ? t('dimensions.locked.passthrough')
    : t('dimensions.locked.noVideo'),
)

const rotations = computed(() =>
  [0, 90, 180, 270].map((degrees) => ({
    value: degrees,
    label: t('dimensions.orientation.degrees', { degrees }),
  })),
)
const pixelAspects = computed(() =>
  (['square', 'keep', 'custom'] as const).map((value) => ({
    value,
    label: t(`dimensions.advanced.pixelAspects.${value}`),
  })),
)
const moduli = [2, 4, 8, 16].map((value) => ({ value, label: String(value) }))
const scalers = computed(() =>
  (['lanczos', 'bicubic', 'spline', 'bilinear'] as const).map((value) => ({
    value,
    label: t(`dimensions.advanced.scalers.${value}`),
  })),
)

const ADVANCED = /^dimensions\.(pixel_aspect|custom_par|modulus|scaler)/
const advancedCollapsed = ref(true)
// A field of the collapsed part that is asked for (an issue's link) opens the part first.
watch(
  () => ui.revealed,
  (request) => {
    if (request !== null && ADVANCED.test(request.path)) advancedCollapsed.value = false
  },
  { immediate: true },
)

function setPixelAspect(value: unknown): void {
  const current = dimensions.value
  if (current === null || value === current.pixel_aspect) return
  if (value === 'custom' && !current.custom_par) {
    editor.patch([
      { op: 'replace', path: '/dimensions/pixel_aspect', value },
      { op: 'add', path: '/dimensions/custom_par', value: { num: 1, den: 1 } },
    ])
    return
  }
  editor.set('/dimensions/pixel_aspect', value)
}

function setPar(part: 'num' | 'den', value: number | null | undefined): void {
  const pointer = `/dimensions/custom_par/${part}`
  if (typeof value === 'number' && value !== editor.get(pointer)) {
    editor.set(pointer, value, { coalesce: pointer })
  }
}
</script>

<template>
  <section ref="root" class="editor-tab dimensions-tab" data-tab="dimensions">
    <p v-if="dimensions === null" class="dimensions-tab__empty" data-state="empty">
      {{ t('dimensions.noJob') }}
    </p>
    <template v-else>
      <div class="dimensions-tab__header">
        <PipelineHeader />
        <p v-if="locked" class="dimensions-tab__locked" data-state="locked">{{ lockedNote }}</p>
      </div>
      <div class="dimensions-tab__content">
        <Section :title="t('dimensions.sections.orientation')">
          <div class="dimensions-tab__row">
            <Field
              :label="t('dimensions.orientation.rotate')"
              path="dimensions.rotate"
              :help="t('dimensions.orientation.rotateHelp')"
              stacked
            >
              <template #default="{ id, labelId }">
                <SelectButton
                  :pt="{ root: { id } }"
                  :model-value="dimensions.rotate"
                  :options="rotations"
                  option-label="label"
                  option-value="value"
                  :allow-empty="false"
                  :disabled="locked"
                  :ariaLabelledby="labelId"
                  data-control="rotate"
                  @update:model-value="editor.set('/dimensions/rotate', $event)"
                />
              </template>
            </Field>
            <Field
              :label="t('dimensions.orientation.flip')"
              path="dimensions.flip_horizontal"
              :help="t('dimensions.orientation.flipHelp')"
              stacked
            >
              <template #default="{ id, labelId }">
                <ToggleSwitch
                  :input-id="id"
                  :model-value="dimensions.flip_horizontal"
                  :disabled="locked"
                  :ariaLabelledby="labelId"
                  data-control="flip"
                  @update:model-value="editor.set('/dimensions/flip_horizontal', $event)"
                />
              </template>
            </Field>
          </div>
        </Section>

        <Section :title="t('dimensions.sections.crop')">
          <CropSection />
        </Section>

        <Section :title="t('dimensions.sections.size')">
          <SizeSection />
        </Section>

        <Section
          v-model:collapsed="advancedCollapsed"
          :title="t('dimensions.sections.advanced')"
          collapsible
        >
          <Field
            :label="t('dimensions.advanced.pixelAspect')"
            path="dimensions.pixel_aspect"
            :help="t('dimensions.advanced.pixelAspectHelp')"
            stacked
          >
            <template #default="{ id, labelId }">
              <SelectButton
                :pt="{ root: { id } }"
                :model-value="dimensions.pixel_aspect"
                :options="pixelAspects"
                option-label="label"
                option-value="value"
                :allow-empty="false"
                :disabled="locked"
                :ariaLabelledby="labelId"
                data-control="pixel-aspect"
                @update:model-value="setPixelAspect"
              />
            </template>
          </Field>
          <Field
            v-if="dimensions.pixel_aspect === 'custom'"
            :label="t('dimensions.advanced.customPar')"
            path="dimensions.custom_par"
            stacked
          >
            <template #default="{ id, invalid }">
              <div class="dimensions-tab__row">
                <InputNumber
                  :input-id="id"
                  :model-value="dimensions.custom_par?.num ?? null"
                  :min="0"
                  :use-grouping="false"
                  :disabled="locked"
                  :ariaLabel="t('dimensions.advanced.parWidth')"
                  :invalid="invalid"
                  data-input="par-num"
                  @update:model-value="setPar('num', $event)"
                />
                <span aria-hidden="true">:</span>
                <InputNumber
                  :model-value="dimensions.custom_par?.den ?? null"
                  :min="1"
                  :use-grouping="false"
                  :disabled="locked"
                  :ariaLabel="t('dimensions.advanced.parHeight')"
                  :invalid="invalid"
                  data-input="par-den"
                  @update:model-value="setPar('den', $event)"
                />
              </div>
            </template>
          </Field>
          <Field
            :label="t('dimensions.advanced.modulus')"
            path="dimensions.modulus"
            :help="t('dimensions.advanced.modulusHelp')"
            stacked
          >
            <template #default="{ id, labelId }">
              <SelectButton
                :pt="{ root: { id } }"
                :model-value="dimensions.modulus"
                :options="moduli"
                option-label="label"
                option-value="value"
                :allow-empty="false"
                :disabled="locked"
                :ariaLabelledby="labelId"
                data-control="modulus"
                @update:model-value="editor.set('/dimensions/modulus', $event)"
              />
            </template>
          </Field>
          <Field
            :label="t('dimensions.advanced.scaler')"
            path="dimensions.scaler"
            :help="t('dimensions.advanced.scalerHelp')"
            stacked
          >
            <template #default="{ id, labelId, invalid }">
              <Select
                :input-id="id"
                :model-value="dimensions.scaler"
                :options="scalers"
                option-label="label"
                option-value="value"
                :disabled="locked"
                :ariaLabelledby="labelId"
                :invalid="invalid"
                data-control="scaler"
                @update:model-value="editor.set('/dimensions/scaler', $event)"
              />
            </template>
          </Field>
        </Section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.dimensions-tab__empty {
  margin: 0;
  padding: var(--rf-space-4);
  color: var(--rf-color-text-muted);
}

/* The pipeline stays in sight while the tab scrolls. */
.dimensions-tab__header {
  position: sticky;
  z-index: 1;
  top: 0;
  padding: var(--rf-space-3) var(--rf-space-4);
  border-bottom: 1px solid var(--rf-color-border);
  background: var(--rf-color-surface);
}

.dimensions-tab__locked {
  margin: var(--rf-space-2) 0 0;
  font-size: var(--rf-font-size-sm);
}

.dimensions-tab__content {
  display: flex;
  flex-direction: column;
  gap: var(--rf-space-5);
  padding: var(--rf-space-4);
}

.dimensions-tab__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--rf-space-2) var(--rf-space-5);
}

.dimensions-tab__row :deep(.p-inputnumber-input) {
  width: 5rem;
}

/* A narrow tab column wraps the segmented controls instead of cutting off their last choices. */
.dimensions-tab :deep(.p-selectbutton) {
  flex-wrap: wrap;
  max-width: 100%;
}

/* The theme greys the text of a disabled choice but keeps the checked one's primary fill, which
   leaves the chosen value unreadable; an outline marks it instead. */
.dimensions-tab :deep(.p-togglebutton-checked:disabled .p-togglebutton-content) {
  background: var(--rf-color-surface);
  box-shadow: inset 0 0 0 1px currentcolor;
}
</style>
