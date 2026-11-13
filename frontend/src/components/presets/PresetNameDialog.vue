<script setup lang="ts">
import Button from 'primevue/button'
import Dialog from 'primevue/dialog'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Textarea from 'primevue/textarea'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { ApiError } from '@/api/client'
import type { ValidationIssue } from '@/api/types'
import Field from '@/components/base/Field.vue'
import { suggestedName, usePresetsStore } from '@/stores/presets'

export interface PresetDetailsInput {
  name: string
  category: string
  description: string
}

/**
 * Name, category and description of a preset: for *Save as new preset* and for *Rename*. `save`
 * rejects with the server's `ApiError`; a name clash shows at the name with the free name the
 * server offers. `closed` comes once the dialog has left the page.
 */
const props = defineProps<{
  /** Already translated. */
  title: string
  /** Already translated. */
  submitLabel: string
  initial: PresetDetailsInput
  save: (details: PresetDetailsInput) => Promise<void>
}>()

const visible = defineModel<boolean>('visible', { required: true })
const emit = defineEmits<{ closed: [] }>()

const { t } = useI18n()
const presets = usePresetsStore()

const name = ref('')
const category = ref('')
const description = ref('')
const busy = ref(false)
const nameIssues = ref<ValidationIssue[]>([])
const offered = ref<string | null>(null)
const failure = ref<string | null>(null)

watch(
  visible,
  (open) => {
    if (!open) return
    name.value = props.initial.name
    category.value = props.initial.category
    description.value = props.initial.description
    nameIssues.value = []
    offered.value = null
    failure.value = null
  },
  { immediate: true },
)

watch(name, () => {
  nameIssues.value = []
  offered.value = null
})

const categories = computed(() => {
  const names = new Set(['Custom', ...presets.categories.map((group) => group.name)])
  return [...names]
})

const canSave = computed(() => name.value.trim() !== '' && !busy.value)

async function submit(): Promise<void> {
  if (!canSave.value) return
  busy.value = true
  failure.value = null
  try {
    await props.save({
      name: name.value.trim(),
      category: category.value.trim() || 'Custom',
      description: description.value,
    })
    visible.value = false
  } catch (error) {
    if (!(error instanceof ApiError)) throw error
    const issues = (error.problem.issues ?? []).filter((issue) => issue.path === 'name')
    if (issues.length > 0) {
      nameIssues.value = issues
      offered.value = suggestedName(error)
    } else {
      failure.value = error.problem.detail ?? error.problem.title
    }
  } finally {
    busy.value = false
  }
}

// PrimeVue's select stops every Escape, also one with its list closed: the dialog would stay.
function categoryKeydown(event: KeyboardEvent): void {
  const field = event.target as Element | null
  if (event.key === 'Escape' && field?.getAttribute('aria-expanded') !== 'true') {
    visible.value = false
  }
}

function useOffered(): void {
  if (offered.value !== null) name.value = offered.value
}
</script>

<template>
  <Dialog
    v-model:visible="visible"
    modal
    :header="title"
    class="preset-name-dialog"
    :style="{ width: 'min(32rem, 95vw)' }"
    @after-hide="emit('closed')"
  >
    <form class="preset-name-dialog__form" @submit.prevent="submit">
      <Field :label="t('presets.dialog.name')" :issues="nameIssues" stacked>
        <template #default="{ id, invalid }">
          <InputText
            :id="id"
            :model-value="name"
            class="preset-name-dialog__name"
            :invalid="invalid"
            autofocus
            fluid
            @update:model-value="name = $event ?? ''"
          />
        </template>
      </Field>
      <Button
        v-if="offered !== null"
        class="preset-name-dialog__offered"
        size="small"
        severity="secondary"
        :label="t('presets.dialog.useName', { name: offered })"
        @click="useOffered"
      />
      <Field :label="t('presets.dialog.category')" stacked>
        <template #default="{ id }">
          <div @keydown.capture="categoryKeydown">
            <Select
              v-model="category"
              :label-id="id"
              class="preset-name-dialog__category"
              :options="categories"
              editable
              fluid
            />
          </div>
        </template>
      </Field>
      <Field :label="t('presets.dialog.description')" stacked>
        <template #default="{ id }">
          <Textarea
            :id="id"
            v-model="description"
            class="preset-name-dialog__description"
            rows="3"
            auto-resize
            fluid
          />
        </template>
      </Field>
      <p v-if="failure" class="preset-name-dialog__failure" role="alert">{{ failure }}</p>
      <div class="preset-name-dialog__actions">
        <Button
          type="button"
          severity="secondary"
          text
          :label="t('presets.dialog.cancel')"
          @click="visible = false"
        />
        <Button
          type="submit"
          class="preset-name-dialog__submit"
          :label="submitLabel"
          :disabled="!canSave"
          :loading="busy"
        />
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.preset-name-dialog__form {
  display: grid;
  gap: var(--rf-space-3);
}

.preset-name-dialog__offered {
  justify-self: start;
}

.preset-name-dialog__failure {
  margin: 0;
  color: var(--p-status-error-color);
}

.preset-name-dialog__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--rf-space-2);
}
</style>
