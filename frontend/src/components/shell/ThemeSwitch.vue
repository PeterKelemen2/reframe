<script setup lang="ts">
import { Palette } from '@lucide/vue'
import Button from 'primevue/button'
import Popover from 'primevue/popover'
import SelectButton from 'primevue/selectbutton'
import vTooltip from 'primevue/tooltip'
import { computed, ref, useId, useTemplateRef } from 'vue'
import { useI18n } from 'vue-i18n'

import { type Density, type ThemeChoice, useTheme } from '@/composables/useTheme'

const { t } = useI18n()
const appearance = useTheme()

const id = useId()
const popover = useTemplateRef<InstanceType<typeof Popover>>('popover')
const open = ref(false)

const themes = computed<{ value: ThemeChoice; label: string }[]>(() => [
  { value: 'system', label: t('shell.theme.system') },
  { value: 'light', label: t('shell.theme.light') },
  { value: 'dark', label: t('shell.theme.dark') },
])
const densities = computed<{ value: Density; label: string }[]>(() => [
  { value: 'comfortable', label: t('shell.theme.comfortable') },
  { value: 'compact', label: t('shell.theme.compact') },
])

const theme = computed({
  get: () => appearance.theme.value,
  set: (value: ThemeChoice) => appearance.setTheme(value),
})
const density = computed({
  get: () => appearance.density.value,
  set: (value: Density) => appearance.setDensity(value),
})
</script>

<template>
  <Button
    v-tooltip.right="t('shell.theme.button')"
    class="theme-switch__button"
    text
    severity="secondary"
    :aria-label="t('shell.theme.button')"
    aria-haspopup="dialog"
    :aria-expanded="open"
    :aria-controls="open ? `${id}-panel` : undefined"
    @click="popover?.toggle($event)"
  >
    <template #icon>
      <Palette :size="20" aria-hidden="true" />
    </template>
  </Button>
  <Popover ref="popover" @show="open = true" @hide="open = false">
    <div
      :id="`${id}-panel`"
      class="theme-switch"
      role="dialog"
      :aria-label="t('shell.theme.title')"
    >
      <span :id="`${id}-theme`" class="theme-switch__label">{{ t('shell.theme.theme') }}</span>
      <SelectButton
        v-model="theme"
        class="theme-switch__theme"
        :options="themes"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        :ariaLabelledby="`${id}-theme`"
      />
      <span :id="`${id}-density`" class="theme-switch__label">{{ t('shell.theme.density') }}</span>
      <SelectButton
        v-model="density"
        class="theme-switch__density"
        :options="densities"
        option-label="label"
        option-value="value"
        :allow-empty="false"
        :ariaLabelledby="`${id}-density`"
      />
    </div>
  </Popover>
</template>

<style scoped>
.theme-switch__button {
  color: var(--rf-color-text-muted);
}

.theme-switch {
  display: grid;
  gap: var(--rf-space-2);
}

.theme-switch__label {
  font-weight: var(--rf-font-weight-medium);
}
</style>
