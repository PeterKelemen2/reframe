<script setup lang="ts">
import { RefreshCw } from '@lucide/vue'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import ToggleSwitch from 'primevue/toggleswitch'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import Field from '@/components/base/Field.vue'
import Section from '@/components/base/Section.vue'
import StatusDot from '@/components/base/StatusDot.vue'
import { useAvailabilityText } from '@/components/video/text'
import { useSystemStore } from '@/stores/system'

import { type EncoderKind, encoderRows, vaapiNodes } from './encoders'
import { useSetting, useSettingsLocked } from './useSetting'

const { t, locale } = useI18n()
const system = useSystemStore()
const locked = useSettingsLocked()
const availabilityText = useAvailabilityText()

const hardwareTests = useSetting<boolean>('/encoders/hardware_tests')
const vaapiDevice = useSetting<string | null>('/encoders/vaapi_device')

const rows = computed(() => encoderRows(system.definitions, system.capabilities))
const detecting = computed(() => system.capabilities?.detecting === true)
const rescanning = ref(false)

const timeFormat = computed(
  () => new Intl.DateTimeFormat(locale.value, { dateStyle: 'short', timeStyle: 'medium' }),
)
function formatTime(value: string | null | undefined): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : timeFormat.value.format(date)
}
const lastCheck = computed(() => formatTime(system.capabilities?.checked_at))

function kindLabel(kind: EncoderKind | null): string {
  switch (kind) {
    case 'software':
      return t('settings.encoders.kind.software')
    case 'nvenc':
      return t('settings.encoders.kind.nvenc')
    case 'qsv':
      return t('settings.encoders.kind.qsv')
    case 'amf':
      return t('settings.encoders.kind.amf')
    case 'vaapi':
      return t('settings.encoders.kind.vaapi')
    case 'audio':
      return t('settings.encoders.kind.audio')
    case null:
      return t('settings.encoders.kind.other')
  }
}

async function rescan(): Promise<void> {
  rescanning.value = true
  try {
    await system.rescanEncoders()
  } catch (error) {
    // The API client has shown it as a toast.
    if (!(error instanceof ApiError)) throw error
  } finally {
    rescanning.value = false
  }
}

const AUTOMATIC = 'auto'
const OTHER = 'other'
/** The user chose to type a node that detection did not list. */
const typing = ref(false)
const typed = ref('')
const currentNode = computed(() => vaapiDevice.value.value?.trim() || null)
const deviceChoice = computed(() => {
  if (typing.value) return OTHER
  return currentNode.value ?? AUTOMATIC
})
const deviceOptions = computed(() => [
  { value: AUTOMATIC, label: t('settings.encoders.vaapiAutomatic') },
  ...vaapiNodes(rows.value, currentNode.value).map((node) => ({ value: node, label: node })),
  { value: OTHER, label: t('settings.encoders.vaapiOther') },
])

async function chooseDevice(choice: string): Promise<void> {
  if (choice === OTHER) {
    typed.value = ''
    typing.value = true
    return
  }
  typing.value = false
  await vaapiDevice.save(choice === AUTOMATIC ? null : choice)
}

async function useTyped(): Promise<void> {
  const node = typed.value.trim()
  if (node === '') return
  // A refused node stays in the field with the server's reason.
  if (await vaapiDevice.save(node)) typing.value = false
}
</script>

<template>
  <Section :title="t('settings.encoders.title')">
    <template #actions>
      <Button
        :label="t('settings.encoders.rescan')"
        severity="secondary"
        outlined
        size="small"
        :loading="rescanning || detecting"
        data-action="rescan"
        @click="rescan"
      >
        <template #icon>
          <RefreshCw :size="16" aria-hidden="true" />
        </template>
      </Button>
    </template>

    <p class="encoders-section__summary" aria-live="polite" data-field="last-check">
      <template v-if="detecting">{{ t('settings.encoders.detecting') }}</template>
      <template v-else-if="lastCheck">{{
        t('settings.encoders.lastCheck', { time: lastCheck })
      }}</template>
      <template v-else>{{ t('settings.encoders.neverChecked') }}</template>
      <template v-if="system.capabilities?.from_cache">
        {{ t('settings.encoders.fromCache') }}</template
      >
    </p>

    <div class="encoders-section__fields">
      <Field
        :label="t('settings.encoders.hardwareTests')"
        :help="t('settings.encoders.hardwareTestsHelp')"
        :issues="hardwareTests.issues.value"
      >
        <template #default="{ id }">
          <ToggleSwitch
            :input-id="id"
            :model-value="hardwareTests.value.value ?? true"
            :disabled="locked"
            data-field="hardware-tests"
            @update:model-value="hardwareTests.save($event)"
          />
        </template>
      </Field>
      <Field
        :label="t('settings.encoders.vaapiDevice')"
        :help="t('settings.encoders.vaapiHelp')"
        :issues="vaapiDevice.issues.value"
      >
        <template #default="{ id, labelId, invalid }">
          <div class="encoders-section__device">
            <Select
              :label-id="id"
              :ariaLabelledby="labelId"
              :model-value="deviceChoice"
              :options="deviceOptions"
              option-label="label"
              option-value="value"
              :invalid="invalid && !typing"
              :disabled="locked"
              data-field="vaapi-device"
              @update:model-value="chooseDevice"
            />
            <template v-if="typing">
              <InputText
                :model-value="typed"
                :aria-label="t('settings.encoders.vaapiNode')"
                :placeholder="t('settings.encoders.vaapiPlaceholder')"
                :invalid="invalid"
                :disabled="locked"
                spellcheck="false"
                autocomplete="off"
                data-field="vaapi-node"
                @update:model-value="typed = $event ?? ''"
                @keydown.enter.prevent="useTyped"
              />
              <Button
                :label="t('settings.encoders.vaapiUse')"
                severity="secondary"
                outlined
                :disabled="locked || typed.trim() === ''"
                :loading="vaapiDevice.saving.value"
                data-action="use-node"
                @click="useTyped"
              />
            </template>
          </div>
        </template>
      </Field>
    </div>

    <div class="encoders-section__table-wrap">
      <table class="encoders-section__table">
        <caption class="rf-sr-only">
          {{
            t('settings.encoders.tableCaption')
          }}
        </caption>
        <thead>
          <tr>
            <th scope="col">{{ t('settings.encoders.column.encoder') }}</th>
            <th scope="col">{{ t('settings.encoders.column.kind') }}</th>
            <th scope="col">{{ t('settings.encoders.column.status') }}</th>
            <th scope="col">{{ t('settings.encoders.column.checked') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.id" :data-encoder="row.id">
            <th scope="row">
              <span class="encoders-section__label">{{ row.label }}</span>
              <code class="encoders-section__id">{{ row.id }}</code>
              <span v-if="row.device" class="encoders-section__node">
                {{ t('settings.encoders.onDevice', { device: row.device }) }}</span
              >
            </th>
            <td>{{ kindLabel(row.kind) }}</td>
            <td data-field="status">
              <StatusDot
                :tone="row.availability.tone"
                :label="availabilityText(row.availability)"
                show-label
              />
            </td>
            <td data-field="checked">
              {{ formatTime(row.checkedAt) ?? t('settings.encoders.notChecked') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </Section>
</template>

<style scoped>
.encoders-section__summary {
  margin: 0;
  color: var(--rf-color-text-muted);
}

.encoders-section__fields {
  display: grid;
  gap: var(--rf-space-3);
}

.encoders-section__device {
  display: flex;
  flex-wrap: wrap;
  gap: var(--rf-space-2);
}

.encoders-section__table-wrap {
  overflow-x: auto;
}

.encoders-section__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--rf-font-size-sm);
}

.encoders-section__table th,
.encoders-section__table td {
  padding: var(--rf-space-2) var(--rf-space-3);
  border-bottom: 1px solid var(--rf-color-border);
  text-align: start;
  vertical-align: top;
}

.encoders-section__table thead th {
  color: var(--rf-color-text-muted);
  font-weight: var(--rf-font-weight-medium);
}

.encoders-section__table tbody th {
  font-weight: var(--rf-font-weight-normal);
}

.encoders-section__table td[data-field='checked'] {
  white-space: nowrap;
}

.encoders-section__label {
  display: block;
  font-weight: var(--rf-font-weight-medium);
}

.encoders-section__id,
.encoders-section__node {
  color: var(--rf-color-text-muted);
  font-size: var(--rf-font-size-xs);
}

.encoders-section__id {
  font-family: var(--rf-font-mono);
}

.encoders-section__node {
  display: block;
}
</style>
