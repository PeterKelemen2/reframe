<script setup lang="ts">
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import { type Density, type ThemeChoice, useTheme } from '@/composables/useTheme'
import { SUPPORTED_LOCALES } from '@/i18n'

import { useSetting, useSettingsLocked } from './useSetting'

const { t, locale } = useI18n()
const appearance = useTheme()
const locked = useSettingsLocked()
const language = useSetting<string>('/appearance/ui_language')

const themes = computed<{ value: ThemeChoice; label: string }[]>(() => [
  { value: 'system', label: t('settings.appearance.theme.system') },
  { value: 'light', label: t('settings.appearance.theme.light') },
  { value: 'dark', label: t('settings.appearance.theme.dark') },
])
const densities = computed<{ value: Density; label: string }[]>(() => [
  { value: 'comfortable', label: t('settings.appearance.density.comfortable') },
  { value: 'compact', label: t('settings.appearance.density.compact') },
])

/** The languages this build has; a saved one it lacks is shown as not available. */
const languages = computed(() => {
  const names = new Intl.DisplayNames([locale.value], { type: 'language' })
  const options: { value: string; label: string; disabled: boolean }[] = SUPPORTED_LOCALES.map(
    (tag) => ({ value: tag, label: names.of(tag) ?? tag, disabled: false }),
  )
  const saved = language.value.value
  if (saved && !options.some((option) => option.value === saved)) {
    const name = names.of(saved) ?? saved
    options.push({
      value: saved,
      label: t('settings.appearance.languageMissing', { language: name }),
      disabled: true,
    })
  }
  return options
})
</script>

<template>
  <Section :title="t('settings.appearance.title')">
    <div class="appearance-section__fields">
      <Field :label="t('settings.appearance.themeLabel')">
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="appearance.theme.value"
            :options="themes"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="locked"
            data-field="theme"
            @update:model-value="appearance.setTheme($event)"
          />
        </template>
      </Field>
      <Field :label="t('settings.appearance.densityLabel')">
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="appearance.density.value"
            :options="densities"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="locked"
            data-field="density"
            @update:model-value="appearance.setDensity($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.appearance.language')"
        :help="t('settings.appearance.languageHelp')"
        :issues="language.issues.value"
      >
        <template #default="{ id, labelId, invalid }">
          <Select
            :label-id="id"
            :ariaLabelledby="labelId"
            :model-value="language.value.value"
            :options="languages"
            option-label="label"
            option-value="value"
            option-disabled="disabled"
            :invalid="invalid"
            :disabled="locked"
            data-field="ui-language"
            @update:model-value="language.save($event)"
          />
        </template>
      </Field>
    </div>
  </Section>
</template>

<style scoped>
.appearance-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}
</style>
