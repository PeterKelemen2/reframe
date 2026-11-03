<script setup lang="ts">
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import type { DesktopSettings, DesktopShell } from '@/platform/types'

/** The desktop shell's own settings (`desktop.json`), not the server's. */
const props = defineProps<{ shell: DesktopShell }>()

const { t } = useI18n()
const saved = ref<DesktopSettings | null>(null)
/** What the switch shows: the wanted value while it is saved, then the saved one. */
const shown = ref(false)
const failure = ref<string | null>(null)
const saving = ref(false)

const issues = computed<ValidationIssue[]>(() =>
  failure.value === null
    ? []
    : [
        {
          severity: 'error',
          code: 'desktop.settings',
          path: 'desktop.tray',
          message: failure.value,
          fixes: [],
        },
      ],
)

onMounted(async () => {
  try {
    saved.value = await props.shell.settings()
    shown.value = saved.value.tray
  } catch (error) {
    failure.value = t('window.settings.unreadable', { reason: String(error) })
  }
})

async function setTray(tray: boolean): Promise<void> {
  if (saved.value === null) return
  shown.value = tray
  saving.value = true
  failure.value = null
  try {
    saved.value = await props.shell.setSettings({ ...saved.value, tray })
  } catch (error) {
    failure.value = t('window.settings.failed', { reason: String(error) })
  } finally {
    saving.value = false
    shown.value = saved.value.tray
  }
}
</script>

<template>
  <Section :title="t('window.settings.title')">
    <Field :label="t('window.settings.tray')" :help="t('window.settings.trayHelp')" :issues>
      <template #default="{ id }">
        <ToggleSwitch
          :input-id="id"
          :model-value="shown"
          :disabled="saved === null || saving"
          data-field="tray"
          @update:model-value="setTray($event)"
        />
      </template>
    </Field>
  </Section>
</template>
