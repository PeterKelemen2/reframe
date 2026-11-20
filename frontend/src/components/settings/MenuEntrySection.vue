<script setup lang="ts">
import Message from 'primevue/message'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import type { DesktopMenuEntry, DesktopShell } from '@/platform/types'

/** The AppImage's entry in the application menu; `entry` is the shell's state when it opened. */
const props = defineProps<{ shell: DesktopShell; entry: DesktopMenuEntry }>()

const { t } = useI18n()
const current = ref<DesktopMenuEntry>(props.entry)
/** What the switch shows: the wanted value while it is saved, then the real one. */
const shown = ref(props.entry.added)
const failure = ref<string | null>(null)
const saving = ref(false)

const issues = computed<ValidationIssue[]>(() =>
  failure.value === null
    ? []
    : [
        {
          severity: 'error',
          code: 'desktop.menu_entry',
          path: 'desktop.menuEntry',
          message: failure.value,
          fixes: [],
        },
      ],
)

async function setAdded(add: boolean): Promise<void> {
  shown.value = add
  saving.value = true
  failure.value = null
  try {
    current.value = await props.shell.setMenuEntry(add)
  } catch (error) {
    failure.value = t('menuEntry.settings.failed', { reason: String(error) })
    current.value = await props.shell.menuEntry().catch(() => current.value)
  } finally {
    saving.value = false
    shown.value = current.value.added
  }
}
</script>

<template>
  <Section :title="t('menuEntry.settings.title')">
    <Message
      v-if="current.other !== null"
      severity="info"
      :closable="false"
      data-field="menu-entry-other"
    >
      {{ t('menuEntry.settings.other', { path: current.other }) }}
    </Message>
    <Field
      v-else
      :label="t('menuEntry.settings.entry')"
      :help="t('menuEntry.settings.help', { file: current.appimage ?? '' })"
      :issues
    >
      <template #default="{ id }">
        <ToggleSwitch
          :input-id="id"
          :model-value="shown"
          :disabled="saving"
          data-field="menu-entry"
          @update:model-value="setAdded($event)"
        />
      </template>
    </Field>
  </Section>
</template>
