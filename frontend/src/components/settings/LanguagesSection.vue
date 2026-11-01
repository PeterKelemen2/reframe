<script setup lang="ts">
import { computed, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import LanguageListEditor from '@/components/language/LanguageListEditor.vue'

import { useSetting, useSettingsLocked } from './useSetting'

const { t } = useI18n()
const locked = useSettingsLocked()

/**
 * A language list setting that shows a change before the server answers, so that a second
 * move or add builds on the first.
 */
function useLanguageList(pointer: string) {
  const setting = useSetting<string[]>(pointer)
  const pending = shallowRef<string[] | null>(null)
  async function save(next: string[]): Promise<void> {
    pending.value = next
    try {
      await setting.save(next)
    } finally {
      if (pending.value === next) pending.value = null
    }
  }
  const value = computed(() => pending.value ?? setting.value.value ?? [])
  return {
    value,
    issues: computed(() => setting.issues.value.map((issue) => plainIssue(issue, value.value))),
    save,
  }
}

/** The server words a tag of the wrong shape as its schema pattern: it gets a sentence. */
function plainIssue(issue: ValidationIssue, list: readonly string[]): ValidationIssue {
  const place = /^languages\.\w+\.(\d+)$/.exec(issue.path)?.[1]
  const tag = place === undefined ? undefined : list[Number(place)]
  if (issue.code !== 'settings.invalid' || tag === undefined) return issue
  return { ...issue, message: t('settings.languages.refusedTag', { tag }) }
}

const favourites = useLanguageList('/languages/favourites')
const preferredAudio = useLanguageList('/languages/preferred_audio')
const preferredSubtitle = useLanguageList('/languages/preferred_subtitle')

const lists = computed(() => [
  {
    key: 'favourites',
    label: t('settings.languages.favourites'),
    help: t('settings.languages.favouritesHelp'),
    setting: favourites,
  },
  {
    key: 'preferred-audio',
    label: t('settings.languages.preferredAudio'),
    help: t('settings.languages.preferredAudioHelp'),
    setting: preferredAudio,
  },
  {
    key: 'preferred-subtitle',
    label: t('settings.languages.preferredSubtitle'),
    help: t('settings.languages.preferredSubtitleHelp'),
    setting: preferredSubtitle,
  },
])
</script>

<template>
  <Section :title="t('settings.languages.title')">
    <div class="languages-section__fields">
      <Field
        v-for="list in lists"
        :key="list.key"
        :label="list.label"
        :help="list.help"
        :issues="list.setting.issues.value"
        stacked
        :data-field="list.key"
      >
        <template #default="{ id, labelId }">
          <LanguageListEditor
            :model-value="list.setting.value.value"
            :label="list.label"
            :input-id="id"
            :labelledby="labelId"
            :disabled="locked"
            @update:model-value="list.setting.save($event)"
          />
        </template>
      </Field>
    </div>
  </Section>
</template>

<style scoped>
.languages-section__fields {
  display: grid;
  gap: var(--rf-space-5);
}
</style>
