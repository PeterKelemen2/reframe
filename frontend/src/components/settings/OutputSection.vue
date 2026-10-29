<script setup lang="ts">
import Select from 'primevue/select'
import SelectButton from 'primevue/selectbutton'
import { computed, useId } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Schemas } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import NamingOptionsEditor from '@/components/naming/NamingOptionsEditor.vue'
import { useSourcesStore } from '@/stores/sources'
import { useSystemStore } from '@/stores/system'

import RefusalList from './RefusalList.vue'
import { useNamingSetting } from './useNamingSetting'
import { useSetting, useSettingsLocked } from './useSetting'

type OutputDefaults = Schemas['OutputDefaults']
type Container = OutputDefaults['default_container']

const { t } = useI18n()
const system = useSystemStore()
const sources = useSourcesStore()
const locked = useSettingsLocked()

const naming = useNamingSetting()
const namingTitle = useId()
const container = useSetting<Container>('/output/default_container')
const collision = useSetting<OutputDefaults['collision']>('/output/collision')
const partialFile = useSetting<OutputDefaults['partial_file']>('/output/partial_file')

/** The preview names the open sources; a source that must be probed again has no values. */
const sourceIds = computed(() =>
  sources.entries.filter((entry) => entry.source !== null).map((entry) => entry.id),
)

const CONTAINERS: readonly Container[] = ['mkv', 'mp4', 'webm']
const containerOptions = computed(() =>
  CONTAINERS.map((id) => ({ value: id, label: system.definitions?.containers?.[id]?.label ?? id })),
)
const collisionOptions = computed(() => [
  { value: 'ask', label: t('settings.output.collision.ask') },
  { value: 'auto_rename', label: t('settings.output.collision.autoRename') },
  { value: 'overwrite', label: t('settings.output.collision.overwrite') },
])
const partialOptions = computed(() => [
  { value: 'delete', label: t('settings.output.partial.delete') },
  { value: 'keep', label: t('settings.output.partial.keep') },
])
</script>

<template>
  <Section :title="t('settings.output.title')">
    <div class="output-section__fields">
      <Field :label="t('settings.output.container')" :issues="container.issues.value">
        <template #default="{ id, invalid }">
          <Select
            :label-id="id"
            :model-value="container.value.value"
            :options="containerOptions"
            option-label="label"
            option-value="value"
            :invalid="invalid"
            :disabled="locked"
            data-field="default-container"
            @update:model-value="container.save($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.output.collisionLabel')"
        :help="t('settings.output.collisionHelp')"
        :issues="collision.issues.value"
      >
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="collision.value.value"
            :options="collisionOptions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="locked"
            data-field="collision"
            @update:model-value="collision.save($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.output.partialLabel')"
        :help="t('settings.output.partialHelp')"
        :issues="partialFile.issues.value"
      >
        <template #default="{ labelId }">
          <SelectButton
            :ariaLabelledby="labelId"
            :model-value="partialFile.value.value"
            :options="partialOptions"
            option-label="label"
            option-value="value"
            :allow-empty="false"
            :disabled="locked"
            data-field="partial-file"
            @update:model-value="partialFile.save($event)"
          />
        </template>
      </Field>
    </div>

    <section class="output-section__naming" :aria-labelledby="namingTitle" data-field="naming">
      <h3 :id="namingTitle" class="output-section__naming-title">
        {{ t('settings.output.naming') }}
      </h3>
      <NamingOptionsEditor
        v-if="naming.naming.value"
        :model-value="naming.naming.value"
        :source-ids="sourceIds"
        :container="container.value.value ?? 'mkv'"
        :disabled="locked"
        @update:model-value="naming.edit"
      />
      <RefusalList :issues="naming.issues.value" />
    </section>
  </Section>
</template>

<style scoped>
.output-section__naming {
  display: grid;
  gap: var(--rf-space-3);
  padding-top: var(--rf-space-3);
  border-top: 1px solid var(--rf-color-border);
}

.output-section__naming-title {
  margin: 0;
  font-size: var(--rf-font-size-md);
}

.output-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}
</style>
